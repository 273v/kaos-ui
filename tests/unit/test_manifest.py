"""Manifest registry tests."""

from __future__ import annotations

import pytest

from kaos_ui.exceptions import UnknownTemplateError
from kaos_ui.manifest import get_manifest, kinds, list_templates, resolve_kind


@pytest.mark.unit
def test_registry_has_phase_0_kinds() -> None:
    registered = set(kinds())
    assert {"web:api", "web:spa", "dashboard:streamlit"}.issubset(registered)


@pytest.mark.unit
def test_list_templates_sorted() -> None:
    manifests = list_templates()
    kind_order = [m.kind for m in manifests]
    assert kind_order == sorted(kind_order)


@pytest.mark.unit
def test_get_manifest_returns_template_directory() -> None:
    m = get_manifest("web:spa")
    assert m.template_dir.name == "spa"
    assert m.template_dir.parent.name == "web"


@pytest.mark.unit
def test_get_manifest_unknown_kind_raises() -> None:
    with pytest.raises(UnknownTemplateError) as excinfo:
        get_manifest("not-a-real-kind")
    msg = str(excinfo.value)
    # Agent-friendly contract: what / how to fix / alternative.
    assert "Unknown template kind" in msg
    assert "How to fix" in msg
    assert "Alternative" in msg


@pytest.mark.unit
@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("api", "web:api"),
        ("app", "web:spa"),
        ("dashboard", "dashboard:streamlit"),
        ("web:spa", "web:spa"),  # canonical pass-through
    ],
)
def test_resolve_kind(legacy: str, canonical: str) -> None:
    assert resolve_kind(legacy) == canonical
