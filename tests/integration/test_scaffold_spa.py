"""Integration test for the web:spa fullstack template (backend slice).

Scaffolds the template, replaces the backend pyproject with a minimal
install set (kaos-core + fastapi + sse-starlette + pydantic), runs
``uv sync`` inside ``backend/``, and runs the scaffolded backend's
deterministic tests (settings + auth + uploads + health).

Frontend build/test is intentionally left for the live tier — pnpm
install pulls hundreds of packages and a vite build is slow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_MINIMAL_BACKEND_DEPS = """\
[project]
name = "{name}-backend"
version = "0.1.0"
description = "{name} backend (test build)"
requires-python = ">=3.13,<3.15"
dependencies = [
  "kaos-core",
  "fastapi>=0.115,<1.0",
  "uvicorn[standard]>=0.32,<1.0",
  "python-multipart>=0.0.20,<1",
  "sse-starlette>=2.1,<3",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.8,<3",
  "python-magic>=0.4.27,<1",
]

[dependency-groups]
dev = [
  "httpx>=0.28,<1",
  "pytest>=8.3,<10",
  "pytest-asyncio>=0.26,<2",
  "pytest-cov>=6.0,<8",
]

[build-system]
requires = ["hatchling>=1.27.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = ["-ra", "--strict-markers"]

[tool.uv.sources]
kaos-core = {{ path = "{kaos_core_path}", editable = true }}
"""


def _have(*tools: str) -> bool:
    return all(shutil.which(t) is not None for t in tools)


def _scaffold(target: Path, name: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            "web:spa",
            name,
            "--target",
            str(target),
        ],
        check=True,
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(not _have("uv"), reason="uv must be on PATH")
@pytest.mark.skipif(
    os.environ.get("KAOS_UI_SKIP_HEAVY_INTEGRATION") == "1",
    reason="KAOS_UI_SKIP_HEAVY_INTEGRATION=1",
)
def test_scaffold_install_and_run_backend_tests(tmp_path: Path) -> None:
    """End-to-end: scaffold → minimal deps → uv sync → pytest backend tests."""
    project = tmp_path / "demo-spa"
    _scaffold(project, "demo-spa")
    backend = project / "backend"
    assert (backend / "app" / "main.py").is_file()

    (backend / "pyproject.toml").write_text(
        _MINIMAL_BACKEND_DEPS.format(name="demo-spa", kaos_core_path=REPO_ROOT / "kaos-core")
    )
    (project / ".env").write_text("APP_AUTH_TOKEN=test-token-do-not-use-in-prod\nAPP_ENV=test\n")

    subprocess.run(
        ["uv", "sync"],
        check=True,
        cwd=backend,
        env={**os.environ, "UV_LINK_MODE": "copy"},
    )
    subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_health.py",
            "tests/test_auth.py",
            "tests/test_uploads.py",
            "tests/test_settings.py",
            "-v",
            "--no-cov",
        ],
        check=True,
        cwd=backend,
    )


@pytest.mark.integration
def test_dry_run_lists_expected_files(tmp_path: Path) -> None:
    """Cheap structural test."""
    from kaos_ui import scaffold

    result = scaffold(
        "web:spa",
        "demo",
        target_dir=tmp_path / "demo",
        dry_run=True,
    )
    files = set(result["files"])
    expected_subset = {
        "backend/app/main.py",
        "backend/app/settings.py",
        "backend/app/auth.py",
        "backend/app/runtime.py",
        "backend/app/exceptions.py",
        "backend/app/logging_setup.py",
        "backend/app/routers/health.py",
        "backend/app/routers/auth.py",
        "backend/app/routers/sessions.py",
        "backend/app/routers/documents.py",
        "backend/app/routers/search.py",
        "backend/app/routers/uploads.py",
        "backend/app/services/chat.py",
        "backend/app/services/uploads.py",
        "backend/tests/test_health.py",
        "backend/tests/test_auth.py",
        "backend/tests/test_uploads.py",
        "backend/tests/test_settings.py",
        "backend/Dockerfile",
        "backend/pyproject.toml",
        ".env.example",
        "Caddyfile",
        "docker-compose.yml",
    }
    missing = expected_subset - files
    assert not missing, f"missing files: {missing}"
