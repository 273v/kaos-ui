"""PROJECT #2 — scaffolder must honor KaosUISettings.

Pre-fix `_build_variables` returned hardcoded "3.14" / "24" regardless
of `KAOS_UI_PYTHON_VERSION` / `KAOS_UI_NODE_VERSION` env vars, and
`templates_dir` (declared in settings) was never read. These tests
prove the settings now flow through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_ui.scaffolder import _build_variables
from kaos_ui.settings import KaosUISettings


def test_build_variables_uses_default_settings() -> None:
    vars_ = _build_variables("my-app", "web:spa")
    assert vars_["KAOS_PYTHON_VERSION"] == "3.14"
    assert vars_["KAOS_NODE_VERSION"] == "24"


def test_build_variables_honors_explicit_settings_override() -> None:
    s = KaosUISettings(python_version="3.13", node_version="22")
    vars_ = _build_variables("my-app", "web:spa", settings=s)
    assert vars_["KAOS_PYTHON_VERSION"] == "3.13"
    assert vars_["KAOS_NODE_VERSION"] == "22"


def test_build_variables_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAOS_UI_PYTHON_VERSION", "3.12")
    monkeypatch.setenv("KAOS_UI_NODE_VERSION", "20")
    s = KaosUISettings()
    assert s.python_version == "3.12"
    assert s.node_version == "20"
    vars_ = _build_variables("my-app", "web:spa", settings=s)
    assert vars_["KAOS_PYTHON_VERSION"] == "3.12"
    assert vars_["KAOS_NODE_VERSION"] == "20"


def test_templates_dir_setting_redirects_template_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An override templates_dir should redirect manifest lookups."""
    from kaos_ui.manifest import _TEMPLATES_ROOT, get_manifest
    from kaos_ui.scaffolder import scaffold

    # Build a minimal "alt" template tree mirroring one shipping kind.
    alt_root = tmp_path / "alt-templates"
    spa_src = _TEMPLATES_ROOT / get_manifest("workflow").template_dir.relative_to(_TEMPLATES_ROOT)
    target = alt_root / spa_src.relative_to(_TEMPLATES_ROOT)
    target.mkdir(parents=True)
    (target / "README.md").write_text("# alt template for {{KAOS_PROJECT_NAME}}\n")

    s = KaosUISettings(templates_dir=alt_root)
    out_dir = tmp_path / "demo"
    result = scaffold("workflow", "demo", target_dir=out_dir, settings=s)

    # The scaffolded README came from the alt root, not the bundled one.
    readme = out_dir / "README.md"
    assert readme.exists()
    assert "alt template for demo" in readme.read_text()
    assert result["template"] == "workflow"
