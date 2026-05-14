"""Single-User Chat backend entrypoint.

Mounts `kaos_agents.api.server.create_app()` and layers our extension
routers on top:

    /v1/health           ← our health router
    /v1/models           ← our model catalog (Phase 1 task #9)
    /v1/chat/*           ← our session sidecar + chat proxy (Phase 1 task #11)

    /v1/sessions/*       ← kaos-agents (mounted by create_app)
    /v1/runs/*/approve   ← kaos-agents
    /openapi.json /docs  ← kaos-agents

See docs/ARCHITECTURE.md § 4.1.
"""

from __future__ import annotations

import httpx
from kaos_agents.api.server import create_app as create_agent_app

from app.logging_setup import app_logger, configure
from app.persistence.sessions import SessionStore
from app.routers import chat, health, models
from app.settings import AppSettings


def create_app(settings: AppSettings | None = None):
    """Build the FastAPI app. Tests call this with a custom ``settings``."""
    settings = settings or AppSettings()
    configure(settings)
    logger = app_logger("main")
    logger.info("startup", extra={"env": settings.env, "default_model": settings.default_model})

    # Kaos-agents reads its own settings (KAOS_AGENTS_API_API_*). We just
    # call its factory — it constructs the FastAPI app for us.
    app = create_agent_app()

    # Hang our state on app.state for dependency lookups.
    app.state.app_settings = settings
    app.state.session_store = SessionStore()
    # In-process httpx client backed by ASGITransport so our proxy
    # routes hit the kaos-agents routes inside this same FastAPI app
    # without touching the real network. Survives both TestClient and
    # real uvicorn runs.
    app.state.upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://kaos-agents.internal",
        timeout=httpx.Timeout(None, connect=10.0),
    )

    # Extension routers — under /v1 to match the kaos-agents route tree.
    app.include_router(health.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")
    app.include_router(chat.router, prefix="/v1/chat")

    return app


app = create_app()
