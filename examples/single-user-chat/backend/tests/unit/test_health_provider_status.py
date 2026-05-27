"""Unit tests for #590 / B1.8 — truthful ``/v1/health``.

Pre-fix: ``app/routers/health.py`` returned HTTP 200 with
``status="ok"`` unconditionally even when zero providers were
configured. A docker-compose healthcheck saw "OK" while every chat
turn failed at the first LLM call.

Post-fix:
- Response includes per-provider ``configured`` / ``unconfigured`` state.
- Returns HTTP 503 ``status="degraded"`` when zero providers are
  configured (so load balancers + monitors can route around).
- Returns HTTP 200 ``status="ok"`` when ≥1 provider is configured.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_provider_status_inventory_covers_kaos_llm_client() -> None:
    """The provider inventory in ``app.routers.health`` must cover
    every provider kaos-llm-client supports today. Regression net for
    a future kaos-llm-client release that adds a provider — the
    health endpoint should at least know about it.
    """
    from app.routers.health import _PROVIDER_ENV_VARS

    inventory = {name for name, _ in _PROVIDER_ENV_VARS}
    # kaos-llm-client 0.1.2 ships these. New providers added in a
    # future release should be added here (and to the inventory).
    expected = {
        "openai",
        "anthropic",
        "google",
        "xai",
        "groq",
        "mistral",
        "openrouter",
    }
    missing = expected - inventory
    assert not missing, f"Health endpoint missing providers: {missing}"


@pytest.mark.unit
def test_provider_status_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When env vars are set, ``_provider_status`` reports `configured`."""
    from app.routers.health import _provider_status

    # Clear all provider env vars; set only OpenAI.
    monkeypatch.delenv("KAOS_LLM_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KAOS_LLM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("KAOS_LLM_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("KAOS_LLM_XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("KAOS_LLM_GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("KAOS_LLM_MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("KAOS_LLM_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-unit-test")

    status_map = _provider_status()
    assert status_map["openai"] == "configured"
    assert status_map["anthropic"] == "unconfigured"
    assert status_map["google"] == "unconfigured"


@pytest.mark.unit
def test_health_degraded_when_no_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero configured providers → HTTP 503 + ``status="degraded"``."""
    # Clear every provider env var we know about.
    from app.routers.health import _PROVIDER_ENV_VARS

    for _, env_vars in _PROVIDER_ENV_VARS:
        for v in env_vars:
            monkeypatch.delenv(v, raising=False)

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/v1/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["reason"] == "no_provider_api_keys_configured"
    assert "providers" in body
    # build_sha still present + non-empty
    assert isinstance(body["build_sha"], str) and len(body["build_sha"]) == 12


@pytest.mark.unit
def test_health_ok_when_at_least_one_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """≥1 configured provider → HTTP 200 + ``status="ok"``."""
    from app.routers.health import _PROVIDER_ENV_VARS

    for _, env_vars in _PROVIDER_ENV_VARS:
        for v in env_vars:
            monkeypatch.delenv(v, raising=False)
    # One provider configured
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["providers"]["anthropic"] == "configured"
    assert body["providers"]["openai"] == "unconfigured"
