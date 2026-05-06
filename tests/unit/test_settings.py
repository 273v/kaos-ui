"""Settings tests."""

from __future__ import annotations

import pytest

from kaos_ui.settings import KaosUISettings


@pytest.mark.unit
def test_defaults() -> None:
    settings = KaosUISettings()
    assert settings.python_version == "3.14"
    assert settings.node_version == "24"
    assert settings.templates_dir is None


@pytest.mark.unit
def test_legacy_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAOS_UI_PYTHON_VERSION", raising=False)
    monkeypatch.delenv("KAOS_UI_NODE_VERSION", raising=False)
    monkeypatch.setenv("KAOS_PYTHON_VERSION", "3.13")
    monkeypatch.setenv("KAOS_NODE_VERSION", "22")
    settings = KaosUISettings()
    assert settings.python_version == "3.13"
    assert settings.node_version == "22"


@pytest.mark.unit
def test_prefixed_env_wins_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAOS_UI_PYTHON_VERSION", "3.14")
    monkeypatch.setenv("KAOS_PYTHON_VERSION", "3.13")
    settings = KaosUISettings()
    assert settings.python_version == "3.14"
