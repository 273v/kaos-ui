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

import contextlib

import httpx
from kaos_agents.api.server import create_app as create_agent_app
from kaos_core.base.context import KaosContext
from kaos_ui.agents import build_chat_runtime

# Note: app._request_ctx.current_tenant_id is no longer read by the
# context_factory below — kaos-agents already scopes session_id via
# scope_session_id() before invoking the factory, so the on-disk path
# layout is encoded into session_id itself. The ContextVar plumbing in
# app/routers/chat.py still sets/resets the value for any other code
# that wants per-request tenant introspection (e.g. logging, telemetry).
from app.logging_setup import app_logger, configure
from app.persistence.sessions import SessionStore
from app.routers import (
    chat,
    citations,
    feedback,
    files,
    health,
    messages,
    models,
    replay,
    runs,
    vfs,
)
from app.settings import AppSettings


# ---------------------------------------------------------------------------
# Per-session ``KaosContext`` factory. The SPA writes uploads into a
# tenant-scoped namespace (``sessions/{tenant}:{sid}/files/`` under bearer
# auth, or ``sessions/{sid}/files/`` in localhost-dev mode — see
# ``app/services/uploads.py::_scoped_session_prefix``). Tool calls that
# accept bare filenames need the same namespace on
# ``context.default_vfs_namespace`` for kaos-core's path resolver to land
# at the on-disk file.
#
# kaos-agents 0.1.14 threads this factory through
# :func:`kaos_agents.api.server.create_app` and stores it on
# ``app.state.context_factory``; the per-request ``Runner(...)``
# constructions at ``/v1/sessions/{id}/messages`` and
# ``/v1/sessions/{id}/runs/{rid}/resume`` both pick it up automatically.
# No host-side patching of Runner internals is required — the
# kaos-agents server picks the factory off ``app.state`` itself.
# ---------------------------------------------------------------------------
def _spa_context_factory(runtime):  # type: ignore[no-untyped-def]
    """Return a ``(session_id) -> KaosContext`` factory closing over ``runtime``.

    The session_id passed in is already in its on-disk-scoped form
    (``{tenant}:{raw_sid}`` under bearer auth, just ``{raw_sid}`` in
    localhost-dev mode) because kaos-agents' route handlers run
    ``scope_session_id(raw_sid, tenant_id)`` before constructing the
    per-request Runner. So we just plug session_id into the namespace
    string verbatim and let kaos-core's path resolver land at the
    on-disk file.
    """

    def _factory(session_id: str) -> KaosContext:
        # kaos-agents' ``/v1/sessions/{id}/messages`` handler ALREADY
        # scopes the session_id via ``scope_session_id(raw_sid, tenant_id)``
        # before constructing the Runner — see
        # ``kaos_agents/api/server.py::start_turn``. So the ``session_id``
        # we receive here is already the on-disk-scoped form
        # ``{tenant}:{raw_sid}`` under bearer-auth mode, or just
        # ``{raw_sid}`` in localhost-dev. Re-prepending the tenant from
        # the ContextVar would produce the double-prefix bug observed in
        # session 01KSBJ5DAYX149A45ER4PK770R (path resolved to
        # ``sessions/{tenant}:{tenant}:{sid}/files/...`` → "not found").
        # Trust the already-scoped session_id and use it verbatim.
        namespace = f"sessions/{session_id}/files/"
        return KaosContext(
            session_id=session_id,
            runtime=runtime,
            vfs=runtime.vfs,
            default_vfs_namespace=namespace,
        )

    return _factory


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

    # kaos-citations + kaos-source are not yet known to kaos-ui 0.1.0a1;
    # register them here. Promote into kaos_ui.agents.build_chat_runtime
    # alongside pdf/office/content when we cut kaos-ui 0.1.0a2 (task #92).
    with contextlib.suppress(ImportError):
        from kaos_citations import register_citations_tools

        register_citations_tools(runtime)
    with contextlib.suppress(ImportError):
        from kaos_source import register_source_tools

        register_source_tools(runtime)
    tool_names = tuple(sorted(runtime.tools.list_tools()))

    # TR-1 + TR-2: partition the now-complete catalog into kaos-agents
    # ToolGroups (web / documents / citations / vfs). SessionMeta.tool_set
    # uses these group names; the stream_proxy resolves the per-session
    # ceiling against the same registry.
    from kaos_ui.agents import register_kaos_tool_groups

    group_counts = register_kaos_tool_groups(runtime)
    logger.info(
        "registered %d kaos tools on runtime; groups=%s",
        len(tool_names),
        ", ".join(f"{g}={n}" for g, n in group_counts.items()) if group_counts else "(none)",
    )

    app = create_agent_app(runtime=runtime, context_factory=_spa_context_factory(runtime))

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
    # SSE resume endpoints (Stage 1) — share the /v1/chat prefix so the
    # ``require_auth`` dependency on every chat route also covers
    # ``/runs/active`` and ``/runs/{run_id}/events``.
    app.include_router(runs.router, prefix="/v1/chat")
    app.include_router(files.router, prefix="/v1/chat")
    app.include_router(vfs.router, prefix="/v1/chat")
    app.include_router(citations.router, prefix="/v1/chat")
    # Plan Issue 10 layer 2 — message-level thumbs feedback.
    app.include_router(feedback.router, prefix="/v1/chat")
    # Plan Issue 6 — court-reproducibility replay endpoint.
    # Mounted under /v1/admin/ rather than /v1/chat/ because replay is
    # operator/audit tooling, not a per-tenant chat surface.
    app.include_router(replay.router, prefix="/v1/admin")
    # Plan Issue 10 L3 + L4 — Regenerate / Edit-prior rewind endpoints.
    app.include_router(messages.router, prefix="/v1/chat")

    return app


app = create_app()
