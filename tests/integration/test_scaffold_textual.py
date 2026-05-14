"""Integration test for the Textual TUI template.

Same minimal-deps pattern as the Streamlit integration test: scaffold,
swap pyproject for a minimal install set, ``uv sync``, run the
deterministic tests inside the scaffolded project.

Smoke tests (which use ``App.run_test()``) are run too — Textual's
headless test harness works in any CI environment without a TTY.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_MINIMAL_DEPS = """\
[project]
name = "{name}"
version = "0.1.0"
description = "{name} (test build)"
requires-python = ">=3.13,<3.15"
dependencies = [
  "kaos-core",
  "textual>=8.0,<9.0",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.8,<3",
]

[dependency-groups]
dev = [
  "pytest>=8.3,<10",
  "pytest-asyncio>=0.26,<2",
  "pytest-cov>=6.0,<8",
]

[build-system]
requires = ["hatchling>=1.27.0"]
build-backend = "hatchling.build"

[project.scripts]
{name} = "{module}.app:run"

[tool.hatch.build.targets.wheel]
packages = ["{module}"]

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = ["-ra", "--strict-markers"]
markers = ["smoke: quick end-to-end checks"]

[tool.uv.sources]
kaos-core = {{ path = "{kaos_core_path}", editable = true }}
"""


def _have(*tools: str) -> bool:
    return all(shutil.which(t) is not None for t in tools)


def _replace_pyproject_with_minimal_deps(project_dir: Path, *, name: str) -> None:
    """Overwrite the scaffolded pyproject with a minimal-dep set.

    The full kaos-* workspace install path has transitive
    ``[tool.uv.sources]`` conflicts (see kaos-ui PATTERNS.md). We test
    the deterministic Python here and let other test layers cover the
    full agent integration.
    """
    pyproject = project_dir / "pyproject.toml"
    module_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    pyproject.write_text(
        _MINIMAL_DEPS.format(
            name=name,
            module=module_name,
            kaos_core_path=REPO_ROOT / "kaos-core",
        )
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    not _have("uv"),
    reason="uv must be on PATH",
)
@pytest.mark.skipif(
    os.environ.get("KAOS_UI_SKIP_HEAVY_INTEGRATION") == "1",
    reason="KAOS_UI_SKIP_HEAVY_INTEGRATION=1 — skipping heavy template tests",
)
@pytest.mark.skipif(
    not (REPO_ROOT / "kaos-core").is_dir(),
    reason="sibling kaos-core checkout not present; this test uses an editable local install",
)
def test_scaffold_install_and_run_template_tests(tmp_path: Path) -> None:
    """End-to-end: scaffold → minimal deps → uv sync → pytest."""
    project = tmp_path / "demo-tui"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            "tui:textual",
            "demo-tui",
            "--target",
            str(project),
        ],
        check=True,
        cwd=tmp_path,
    )
    assert (project / "demo_tui" / "app.py").is_file()
    assert (project / "demo_tui" / "screens" / "chat.py").is_file()

    _replace_pyproject_with_minimal_deps(project, name="demo-tui")

    subprocess.run(
        ["uv", "sync"],
        check=True,
        cwd=project,
        env={
            **os.environ,
            "UV_LINK_MODE": "copy",
            # Stable terminal env for the smoke tests, just in case.
            "TERM": "xterm-256color",
        },
    )

    subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_settings.py",
            "tests/test_services.py",
            "tests/test_smoke.py",
            "-v",
            "--no-cov",
        ],
        check=True,
        cwd=project,
        env={**os.environ, "TERM": "xterm-256color"},
    )


@pytest.mark.integration
def test_dry_run_lists_expected_files(tmp_path: Path) -> None:
    """Cheap structural test."""
    from kaos_ui import scaffold

    result = scaffold(
        "tui:textual",
        "demo",
        target_dir=tmp_path / "demo",
        dry_run=True,
    )
    files = set(result["files"])
    expected_subset = {
        "demo/app.py",
        "demo/__main__.py",
        "demo/settings.py",
        "demo/runtime.py",
        "demo/exceptions.py",
        "demo/logging_setup.py",
        "demo/styles.tcss",
        "demo/screens/chat.py",
        "demo/screens/documents.py",
        "demo/screens/settings.py",
        "demo/services/chat.py",
        "demo/services/documents.py",
        "tests/test_smoke.py",
        "tests/test_settings.py",
        "tests/test_services.py",
        "Makefile",
        "pyproject.toml",
        ".env.example",
    }
    missing = expected_subset - files
    assert not missing, f"missing files: {missing}"
