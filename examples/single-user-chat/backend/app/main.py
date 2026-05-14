"""Single-User Chat backend entrypoint.

Mounts `kaos_agents.api.server.create_app()` and layers our extension
routers on top:

    /v1/health           ← our health router
    /v1/models           ← our model catalog
    /v1/chat/*           ← our session sidecar + chat proxy

    /v1/sessions/*       ← kaos-agents (mounted by create_app)
    /v1/runs/*/approve   ← kaos-agents
    /openapi.json /docs  ← kaos-agents

CRITICAL — kaos-agents' `create_app()` defaults to an in-memory VFS
when called without an explicit runtime (see `kaos_agents/api/server.py`
`_resolve_vfs`: `VFSConfig(default_backend=StorageBackend.MEMORY)`).
That means every conversation evaporates on process restart. We pass
a disk-backed `KaosRuntime` explicitly so SessionMemory persists at
`{vfs_path}/kaos-agents/sessions/{id}/`.

See docs/PATTERNS.md P-020.
"""

from __future__ import annotations

import httpx
from kaos_agents.api.server import create_app as create_agent_app
from kaos_core import KaosRuntime
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from kaos_core.vfs.models import IsolationMode

from app.logging_setup import app_logger, configure
from app.persistence.sessions import SessionStore
from app.routers import chat, health, models
from app.settings import AppSettings


def _install_tool_bridge_runtime_patch() -> None:
    """Workaround for an upstream kaos-agents 0.1.0a1 gap.

    The bundled `Runner` only constructs a `KaosContext` when `corpus is
    not None`. With `corpus=None` (our case — pure chat without RAG) the
    context passed to `bridge_runtime_tools` is `None`, which means the
    bridged tool wrappers have no `KaosContext` with a `.runtime`
    attached at execution time, so every tool call returns
    `{"error": true, "message": "No runtime context..."}` — see
    docs/PATTERNS.md P-021.

    Fix: wrap `bridge_runtime_tools` so it auto-creates a context with
    the runtime when none is supplied. Idempotent — runs once at import
    of `app.main`.
    """
    from kaos_agents.actions import tool_bridge
    from kaos_core.base.context import KaosContext

    if getattr(tool_bridge, "_chat_example_patched", False):
        return

    _original = tool_bridge.bridge_runtime_tools

    def patched(runtime, context=None, **kwargs):
        if context is None:
            context = KaosContext.create(runtime=runtime)
        return _original(runtime, context, **kwargs)

    tool_bridge.bridge_runtime_tools = patched  # ty: ignore[invalid-assignment]
    tool_bridge._chat_example_patched = True  # ty: ignore[unresolved-attribute]
    # Also patch the symbol that runner imports lazily.
    import kaos_agents.runtime.runner as runner_mod

    if hasattr(runner_mod, "bridge_runtime_tools"):
        runner_mod.bridge_runtime_tools = patched


_install_tool_bridge_runtime_patch()


def _build_disk_runtime(settings: AppSettings) -> KaosRuntime:
    """Construct a KaosRuntime backed by a disk VFS so kaos-agents
    SessionMemory survives process restarts AND register the read-only
    KAOS tool surface so the agent can actually use tools when the
    session has tools_enabled=True.

    Each tool group is registered behind `contextlib.suppress(ImportError)`
    so a slimmed deployment without the optional kaos-pdf / kaos-office /
    kaos-content extras still boots — the tools just don't show up.
    Mirrors the pattern in `templates/web/spa/backend/app/runtime.py.tmpl`.
    """
    import contextlib

    from app.logging_setup import app_logger as _alog

    log = _alog("runtime")

    vfs = VirtualFileSystem(
        config=VFSConfig(
            disk_base_path=settings.vfs_path,
            isolation_mode=IsolationMode.GLOBAL,
        ),
    )
    runtime = KaosRuntime(vfs=vfs)

    total = 0

    # Core tools always available (filesystem reads, etc.).
    with contextlib.suppress(ImportError):
        from kaos_core.tools import register_core_tools

        total += register_core_tools(runtime)

    # Optional extras — only if the package is installed.
    with contextlib.suppress(ImportError):
        from kaos_pdf import register_pdf_tools

        total += register_pdf_tools(runtime)

    with contextlib.suppress(ImportError):
        from kaos_office import register_office_tools

        total += register_office_tools(runtime)

    with contextlib.suppress(ImportError):
        from kaos_content.tools import register_content_tools

        total += register_content_tools(runtime)

    log.info("registered %d tools on runtime", total)
    return runtime


def create_app(settings: AppSettings | None = None):
    """Build the FastAPI app. Tests call this with a custom ``settings``."""
    settings = settings or AppSettings()
    configure(settings)
    logger = app_logger("main")
    logger.info(
        "startup",
        extra={
            "env": settings.env,
            "default_model": settings.default_model,
            "vfs_path": str(settings.vfs_path),
        },
    )

    runtime = _build_disk_runtime(settings)
    app = create_agent_app(runtime=runtime)

    app.state.app_settings = settings
    app.state.kaos_runtime = runtime
    # SessionStore reuses the same VFS so our metadata sidecar lives
    # alongside kaos-agents memory under the same .kaos-vfs/ root.
    app.state.session_store = SessionStore(vfs=runtime.vfs)
    app.state.upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://kaos-agents.internal",
        timeout=httpx.Timeout(None, connect=10.0),
    )

    app.include_router(health.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")
    app.include_router(chat.router, prefix="/v1/chat")

    return app


app = create_app()
