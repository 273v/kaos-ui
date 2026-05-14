"""Integration test for the Streamlit template.

Scaffolds the template into a tmpdir, replaces its dependencies with a
minimal install set, runs ``uv sync``, and runs the deterministic
subset of the scaffolded project's tests (settings + auth + uploads —
they don't need the full KAOS stack).

The full end-to-end "real KAOS workspace install" path is not tested
here because the kaos-* packages aren't on PyPI yet AND their
transitive ``[tool.uv.sources]`` conflict with absolute-path overrides
applied at the scaffolded-project level. That belongs in a CI test
running inside the kaos-modules workspace with the live pyproject
intact, not in a per-template integration test.

Marked ``slow`` because uv sync hits PyPI on a cold cache.
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
"""The kaos-modules workspace root."""

_MINIMAL_DEPS = """\
[project]
name = "{name}"
version = "0.1.0"
description = "{name} (test build)"
requires-python = ">=3.13,<3.15"
dependencies = [
  "kaos-core",
  "streamlit>=1.50,<2.0",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.8,<3",
]

[dependency-groups]
dev = [
  "pytest>=8.3,<10",
  "pytest-cov>=6.0,<8",
]

[build-system]
requires = ["hatchling>=1.27.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{module}"]

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers"]
markers = ["smoke: quick end-to-end checks"]

[tool.uv.sources]
kaos-core = {{ path = "{kaos_core_path}", editable = true }}
"""


def _have(*tools: str) -> bool:
    return all(shutil.which(t) is not None for t in tools)


def _replace_pyproject_with_minimal_deps(project_dir: Path, *, name: str) -> None:
    """Overwrite the scaffolded pyproject with a minimal dep set for testing.

    The scaffolded project depends on six kaos-* packages, only one of
    which (kaos-core) is on PyPI. Wiring up the full workspace install
    is out of scope for a per-template integration test. We test the
    deterministic Python — settings refusal, auth comparison, upload
    validation — none of which need the heavy KAOS stack.
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

    # Drop the project's smoke test from the test set we run here — it
    # boots Streamlit's AppTest which imports app.py which transitively
    # imports services/chat.py (kaos-agents). The deterministic
    # settings/auth/uploads tests don't pull in the heavy stack and
    # are the right gate for this minimal-deps run.
    smoke = project_dir / "tests" / "test_smoke.py"
    if smoke.exists():
        smoke.unlink()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    not _have("uv"),
    reason="uv must be on PATH; install via `curl -LsSf https://astral.sh/uv/install.sh | sh`",
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
    """End-to-end: scaffold → minimal deps → uv sync → run deterministic tests."""
    project = tmp_path / "demo-board"

    # 1. Scaffold via the kaos-ui CLI.
    scaffold_cmd = [
        sys.executable,
        "-m",
        "kaos_ui",
        "new",
        "dashboard:streamlit",
        "demo-board",
        "--target",
        str(project),
    ]
    subprocess.run(scaffold_cmd, check=True, cwd=tmp_path)
    assert (project / "app.py").is_file()
    assert (project / "demo_board" / "settings.py").is_file()

    # 2. Replace pyproject with a minimal install set; drop tests that
    #    need the heavy KAOS stack.
    _replace_pyproject_with_minimal_deps(project, name="demo-board")

    # 3. Write a test .env so AppSettings doesn't refuse to load.
    (project / ".env").write_text("APP_AUTH_TOKEN=test-token-do-not-use-in-prod\nAPP_ENV=test\n")

    # 4. uv sync.
    subprocess.run(
        ["uv", "sync"],
        check=True,
        cwd=project,
        env={**os.environ, "UV_LINK_MODE": "copy"},
    )

    # 5. Run the deterministic tests (settings + auth + uploads).
    subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_settings.py",
            "tests/test_auth.py",
            "tests/test_uploads.py",
            "-v",
            "--no-cov",
        ],
        check=True,
        cwd=project,
    )


@pytest.mark.integration
def test_dry_run_lists_expected_files(tmp_path: Path) -> None:
    """Cheap test: confirm the scaffolder would emit the canonical layout."""
    from kaos_ui import scaffold

    result = scaffold(
        "dashboard:streamlit",
        "demo",
        target_dir=tmp_path / "demo",
        dry_run=True,
    )
    files = set(result["files"])
    expected_subset = {
        "app.py",
        "demo/settings.py",
        "demo/auth.py",
        "demo/runtime.py",
        "demo/services/chat.py",
        "demo/services/uploads.py",
        "pages/chat.py",
        "pages/upload.py",
        "tests/test_smoke.py",
        "Dockerfile",
        "Makefile",
        "docker-compose.yml",
        ".env.example",
        "pyproject.toml",
    }
    missing = expected_subset - files
    assert not missing, f"missing files: {missing}"
