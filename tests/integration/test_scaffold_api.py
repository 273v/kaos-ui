"""Integration test for the web:api FastAPI template.

Scaffolds the web:api kind, replaces the rendered pyproject with a
minimal install set (FastAPI + httpx + pytest), runs `uv sync`, then
runs the scaffolded `tests/` against the rendered backend to confirm
the FastAPI app boots end-to-end.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_MINIMAL_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
description = "{name} api (test build)"
requires-python = ">=3.13,<3.15"
dependencies = [
  "fastapi[standard]>=0.115,<1.0",
]

[dependency-groups]
dev = [
  "pytest>=8.3,<10",
  "pytest-asyncio>=0.26,<2",
  "pytest-cov>=6.0,<8",
  "httpx>=0.28,<1",
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
            "web:api",
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
def test_scaffold_install_and_run_tests(tmp_path: Path) -> None:
    """End-to-end: scaffold → minimal deps → uv sync → pytest tests/."""
    project = tmp_path / "demo-api"
    _scaffold(project, "demo-api")

    pyproject = project / "pyproject.toml"
    assert pyproject.is_file(), "web:api must emit a pyproject.toml"
    assert (project / "app" / "main.py").is_file(), "web:api must emit app/main.py"

    pyproject.write_text(_MINIMAL_PYPROJECT.format(name="demo-api"))

    subprocess.run(
        ["uv", "sync", "--group", "dev"],
        check=True,
        cwd=project,
        env={**os.environ, "UV_LINK_MODE": "copy"},
    )

    # Boot probe: import the app and hit /health via TestClient.
    smoke = project / "tests" / "test_smoke.py"
    smoke.write_text(
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "\n"
        "def test_healthz_returns_200():\n"
        "    with TestClient(app) as client:\n"
        "        r = client.get('/health')\n"
        "        assert r.status_code == 200\n"
    )
    subprocess.run(
        ["uv", "run", "pytest", "tests/test_smoke.py", "-v", "--no-cov"],
        check=True,
        cwd=project,
    )


@pytest.mark.integration
def test_dry_run_lists_expected_files(tmp_path: Path) -> None:
    """Cheap structural check: scaffold dry-run lists the expected entrypoints."""
    from kaos_ui import scaffold

    result = scaffold(
        "web:api",
        "demo",
        target_dir=tmp_path / "demo",
        dry_run=True,
    )
    files = set(result.files)
    expected_subset = {
        "app/main.py",
        "pyproject.toml",
        "README.md",
    }
    missing = expected_subset - files
    assert not missing, f"missing files: {missing}"
