"""FastAPI dependency providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    import httpx
    from kaos_core import KaosRuntime

    from app.persistence.sessions import SessionStore
    from app.settings import AppSettings


def get_settings(request: Request) -> AppSettings:
    """Per-request access to the app's resolved settings."""
    return request.app.state.app_settings


def get_session_store(request: Request) -> SessionStore:
    """Per-request access to the session metadata store."""
    return request.app.state.session_store


def get_upstream_client(request: Request) -> httpx.AsyncClient:
    """In-process httpx client (ASGITransport) to the kaos-agents routes."""
    return request.app.state.upstream_client


def get_runtime(request: Request) -> KaosRuntime:
    """Per-request access to the shared KaosRuntime (VFS + tools)."""
    return request.app.state.kaos_runtime
