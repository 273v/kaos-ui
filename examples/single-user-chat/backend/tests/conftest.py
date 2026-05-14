"""Shared fixtures.

Most tests build a fresh FastAPI app per test so on-disk state doesn't
leak between tests. The `KAOS_AGENTS_API_API_TOKEN` env var must be set
before importing `kaos_agents.api.server` — see docs/PATTERNS.md P-001/P-002.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "test-token-must-be-at-least-32-chars-long-or-validation-fails"


@pytest.fixture(autouse=True, scope="session")
def _silence_kaos_logs() -> None:
    """Keep kaos-agents/llm-client INFO noise out of pytest output."""
    logging.getLogger("kaos").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


@pytest.fixture(autouse=True, scope="session")
def _api_token_env() -> None:
    """The bearer token must exist before create_app() is called."""
    os.environ["KAOS_AGENTS_API_API_TOKEN"] = TEST_TOKEN
    os.environ["APP_ENV"] = "test"


@pytest.fixture
def tmp_vfs_path(tmp_path: Path) -> Iterator[Path]:
    """A temp directory used as the VFS base for an isolated test."""
    yield tmp_path / ".kaos-vfs"


@pytest.fixture
def session_store(tmp_vfs_path: Path) -> Any:
    """A `SessionStore` against a temp VFS — no state leak between tests."""
    from kaos_core.vfs import VFSConfig, VirtualFileSystem
    from kaos_core.vfs.models import IsolationMode

    from app.persistence.sessions import SessionStore

    cfg = VFSConfig(disk_base_path=tmp_vfs_path, isolation_mode=IsolationMode.GLOBAL)
    return SessionStore(vfs=VirtualFileSystem(config=cfg))


@pytest.fixture
def app(tmp_vfs_path: Path):
    """Fresh FastAPI app with a temp VFS for the session store."""
    # Each test that uses ``app`` gets a fresh import to avoid the
    # module-level ``app = create_app()`` singleton in main.py.
    import importlib

    from kaos_core.vfs import VFSConfig, VirtualFileSystem
    from kaos_core.vfs.models import IsolationMode

    import app.main as app_module
    from app.persistence.sessions import SessionStore
    from app.settings import AppSettings

    importlib.reload(app_module)
    settings = AppSettings(env="test")
    a = app_module.create_app(settings)

    # Override the session store with our temp-VFS one.
    cfg = VFSConfig(disk_base_path=tmp_vfs_path, isolation_mode=IsolationMode.GLOBAL)
    a.state.session_store = SessionStore(vfs=VirtualFileSystem(config=cfg))
    return a


@pytest.fixture
def _reset_sse_exit_event() -> None:
    """Workaround for sse-starlette's module-global `AppStatus.should_exit_event`.

    The event is created on first import. Under TestClient + per-test
    event loops the second test sees the event bound to a stale loop and
    raises `RuntimeError: ... is bound to a different event loop`. We
    null it so sse-starlette creates a fresh one on the current loop.
    """
    try:
        import sse_starlette.sse as sse

        if hasattr(sse, "AppStatus"):
            sse.AppStatus.should_exit_event = None
    except Exception:
        pass


@pytest.fixture
def client(app, _reset_sse_exit_event) -> TestClient:
    """Authenticated TestClient — `Authorization: Bearer …` header preset."""
    return TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"})
