"""Model catalog registry-guard tests.

These exist explicitly to fail loudly when a model id falls out of
`kaos_llm_client.cost.MODEL_PRICING` — e.g., when kaos-llm-client
publishes a new release that retires an id we hardcoded.
"""

from __future__ import annotations

import pytest
from kaos_llm_client.cost import MODEL_PRICING

from app.services.catalog import _CURATED, _strip_provider, build_catalog

pytestmark = pytest.mark.unit


def test_build_catalog_returns_curated():
    entries = build_catalog()
    assert len(entries) == len(_CURATED)
    ids = {e.id for e in entries}
    assert ids == {row[0] for row in _CURATED}


def test_all_ids_in_provider_model_format():
    for entry in build_catalog():
        assert ":" in entry.id
        provider, model = entry.id.split(":", 1)
        assert provider in {"anthropic", "openai", "google", "xai"}
        assert model  # not empty


def test_all_ids_present_in_model_pricing_registry():
    """Registry guard: every curated id MUST be in MODEL_PRICING."""
    registry = set(MODEL_PRICING.keys())
    for entry in build_catalog():
        model_part = _strip_provider(entry.id)
        assert model_part in registry, (
            f"catalog rot: {entry.id!r} (model={model_part!r}) is not in "
            f"kaos_llm_client.cost.MODEL_PRICING. "
            f"Update backend/app/services/catalog.py."
        )


def test_default_model_in_catalog():
    """The AppSettings default must be one of the picker entries."""
    from app.settings import AppSettings

    s = AppSettings(env="test")
    catalog_ids = {e.id for e in build_catalog()}
    assert s.default_model in catalog_ids, (
        f"AppSettings.default_model={s.default_model!r} is not in the "
        f"picker catalog. Either change the default or add an entry."
    )


def test_labels_unique():
    labels = [e.label for e in build_catalog()]
    assert len(labels) == len(set(labels)), "duplicate label in catalog"


def test_providers_are_typed_literal():
    """ModelEntry.provider must be the Literal we promised in models.py."""
    valid = {"anthropic", "openai", "google", "xai"}
    for entry in build_catalog():
        assert entry.provider in valid
