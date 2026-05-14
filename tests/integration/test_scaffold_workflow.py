"""Integration test for the workflow template.

Scaffolds the workflow kind, runs `uv sync` against a minimal
single-file dependency set, then executes the generated `main.py`
to confirm the rendered template boots end-to-end.
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
description = "{name} workflow (test build)"
requires-python = ">=3.13,<3.15"
dependencies = [
  "kaos-core",
]

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
            "workflow",
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
@pytest.mark.skipif(
    not (REPO_ROOT / "kaos-core").is_dir(),
    reason="sibling kaos-core checkout not present; this test uses an editable local install",
)
def test_scaffold_install_and_run_main(tmp_path: Path) -> None:
    """End-to-end: scaffold → swap to minimal deps → uv sync → run main.py."""
    project = tmp_path / "demo-wf"
    _scaffold(project, "demo-wf")

    main_py = project / "main.py"
    assert main_py.is_file(), "scaffolded workflow must have a main.py at root"

    pyproject = project / "pyproject.toml"
    if pyproject.is_file():
        pyproject.write_text(
            _MINIMAL_PYPROJECT.format(name="demo-wf", kaos_core_path=REPO_ROOT / "kaos-core")
        )
    else:
        # Workflow kind may emit a script-only layout without a pyproject;
        # write one so uv has something to resolve against.
        pyproject.write_text(
            _MINIMAL_PYPROJECT.format(name="demo-wf", kaos_core_path=REPO_ROOT / "kaos-core")
        )

    subprocess.run(
        ["uv", "sync"],
        check=True,
        cwd=project,
        env={**os.environ, "UV_LINK_MODE": "copy"},
    )
    # The workflow main.py expects a PDF arg and exits 1 with a Usage
    # message when missing — that proves it imports + runs without
    # crashing on a missing dep or syntax error.
    completed = subprocess.run(
        ["uv", "run", "python", "main.py"],
        check=False,
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "Usage:" in completed.stdout, (
        f"main.py did not print the usage banner.\n"
        f"exit: {completed.returncode}\n"
        f"stdout: {completed.stdout!r}\n"
        f"stderr: {completed.stderr!r}"
    )


@pytest.mark.integration
def test_dry_run_lists_expected_files(tmp_path: Path) -> None:
    """Cheap structural check: scaffold dry-run lists the expected entrypoints."""
    from kaos_ui import scaffold

    result = scaffold(
        "workflow",
        "demo",
        target_dir=tmp_path / "demo",
        dry_run=True,
    )
    files = set(result.files)
    # Workflow is a single-file script + minimal scaffolding.
    assert "main.py" in files, f"missing main.py; got: {files}"
    assert len(files) >= 1
