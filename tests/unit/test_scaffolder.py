"""Scaffolder unit tests.

Phase 0 covers the slugifier, the variable substitution path, and the
dry-run output. Live install/build runs live in
``tests/integration/test_scaffold_*.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_ui.exceptions import TargetExistsError, UnknownTemplateError
from kaos_ui.scaffolder import _slugify, scaffold


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("My App", "my_app"),
        ("kaos-test-thing", "kaos_test_thing"),
        ("__weird---name__", "weird_name"),
        ("Foo Bar 123", "foo_bar_123"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert _slugify(name) == expected


@pytest.mark.unit
def test_unknown_template_raises() -> None:
    with pytest.raises(UnknownTemplateError):
        scaffold("not-a-kind", "demo", dry_run=True)


@pytest.mark.unit
def test_dry_run_returns_files_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "out"
    result = scaffold("dashboard:streamlit", "demo", target_dir=target, dry_run=True)
    assert result["dry_run"] is True
    assert result["template"] == "dashboard:streamlit"
    assert result["files"]
    assert not target.exists()


@pytest.mark.unit
def test_legacy_kind_resolves(tmp_path: Path) -> None:
    target = tmp_path / "out"
    result_legacy = scaffold("dashboard", "demo", target_dir=target, dry_run=True)
    result_canonical = scaffold("dashboard:streamlit", "demo", target_dir=target, dry_run=True)
    assert result_legacy["files"] == result_canonical["files"]
    assert result_legacy["template"] == "dashboard:streamlit"


@pytest.mark.unit
def test_target_must_be_empty(tmp_project_root: Path) -> None:
    (tmp_project_root / "preexisting.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(TargetExistsError):
        scaffold("dashboard:streamlit", "demo", target_dir=tmp_project_root)
