"""Single-User Chat backend entrypoint.

Mounts `kaos_agents.api.server.create_app()` and layers our extension
routers on top:

    /v1/health           ← our health router
    /v1/models           ← our model catalog
    /v1/chat/*           ← our session sidecar + chat proxy

    /v1/sessions/*       ← kaos-agents (mounted by create_app)
    /v1/runs/*/approve   ← kaos-agents
    /openapi.json /docs  ← kaos-agents

The disk-backed runtime, the kaos-agents `bridge_runtime_tools` patch,
and the optional kaos-pdf / kaos-office / kaos-content tool surface
are all delegated to `kaos_ui.agents.build_chat_runtime`, which is the
canonical home for these "kaos-agents 0.1.0a1 on FastAPI" workarounds.
See `kaos-ui` README and the upstream issues filed on 273v/kaos-agents
(#16 fixed in kaos-agents main, #17 + #18 pending design review) — once
those land, the workarounds inside `kaos_ui.agents` will simplify in
the next kaos-ui release.
"""

from __future__ import annotations

import httpx
from kaos_agents.api.server import create_app as create_agent_app
from kaos_ui.agents import build_chat_runtime

from app.logging_setup import app_logger, configure
from app.persistence.sessions import SessionStore
from app.routers import chat, files, health, models
from app.settings import AppSettings


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

    # kaos_ui.agents.build_chat_runtime: returns a disk-backed KaosRuntime
    # with kaos-core + (optional) kaos-pdf / kaos-office / kaos-content
    # read tools registered, plus the install_tool_bridge_runtime_patch
    # workaround applied idempotently. `tool_names` is the sorted catalog
    # used downstream by the system-prompt augmentation in stream_proxy.
    runtime, tool_names = build_chat_runtime(vfs_path=settings.vfs_path)
    logger.info("registered %d kaos tools on runtime", len(tool_names))

    app = create_agent_app(runtime=runtime)

    app.state.app_settings = settings
    app.state.kaos_runtime = runtime
    app.state.kaos_tool_names = tool_names
    # SessionStore reuses the same VFS so our metadata sidecar lives
    # alongside kaos-agents memory under the same .kaos-vfs/ root.
    app.state.session_store = SessionStore(vfs=runtime.vfs)

    # In-process httpx client (ASGITransport) for the chat proxy.
    # Constructed eagerly so the first request doesn't wait, and
    # closed on shutdown via FastAPI's event hook.
    app.state.upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://kaos-agents.internal",
        timeout=httpx.Timeout(None, connect=10.0),
    )

    # `on_event("shutdown")` is the deprecated-but-still-supported way
    # to hook teardown on a FastAPI app we don't own (create_agent_app
    # installed its own lifespan; composing a second one cleanly would
    # require subclassing).
    @app.on_event("shutdown")  # ty: ignore[deprecated]
    async def _close_upstream_client() -> None:
        client = getattr(app.state, "upstream_client", None)
        if client is not None:
            await client.aclose()

    app.include_router(health.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")
    app.include_router(chat.router, prefix="/v1/chat")
    app.include_router(files.router, prefix="/v1/chat")

    return app


app = create_app()
