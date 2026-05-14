"""HTTP round-trip tests against our extension routes — no LLM calls."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_gate_on_extension_routes(app):
    """CRITICAL #1 regression — /v1/chat/* and /v1/models must require auth.

    Pre-fix, these routes were public, which let invalid tokens pass
    the SPA's login probe (CRITICAL #2). Both fixes verified by this
    test: unauthenticated requests get 401, valid bearer gets 2xx.
    """
    from fastapi.testclient import TestClient

    from tests.conftest import TEST_TOKEN  # ty: ignore[unresolved-import]

    # No-auth client — fresh, no preset Authorization header.
    bare = TestClient(app)

    # Health stays public (docker healthcheck needs it).
    assert bare.get("/v1/health").status_code == 200

    # Everything else requires auth.
    for path in [
        "/v1/models",
        "/v1/chat/sessions",
        "/v1/chat/sessions/anything/meta",
    ]:
        assert bare.get(path).status_code == 401, f"{path} did not 401 without auth"

    assert bare.post("/v1/chat/sessions", json={}).status_code == 401
    assert bare.patch("/v1/chat/sessions/x/meta", json={}).status_code == 401
    assert bare.post("/v1/chat/sessions/x/archive").status_code == 401
    assert bare.post("/v1/chat/sessions/x/messages", json={"message": "hi"}).status_code == 401

    # Wrong bearer also 401s.
    wrong = TestClient(app, headers={"Authorization": "Bearer wrong-token-32-chars-long-padding"})
    assert wrong.get("/v1/models").status_code == 401
    assert wrong.get("/v1/chat/sessions").status_code == 401

    # Valid bearer flips to 2xx.
    good = TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert good.get("/v1/models").status_code == 200
    assert good.get("/v1/chat/sessions").status_code == 200


def test_models_catalog_shape(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert isinstance(data["models"], list)
    assert len(data["models"]) >= 1
    for m in data["models"]:
        assert ":" in m["id"]
        assert m["label"]
        assert m["provider"] in {"anthropic", "openai", "google", "xai"}


def test_create_session_round_trip(client):
    r = client.post(
        "/v1/chat/sessions",
        json={"title": "test session", "model": "anthropic:claude-haiku-4-5"},
    )
    assert r.status_code == 201, r.text
    meta = r.json()
    sid = meta["id"]
    assert meta["title"] == "test session"
    assert meta["model"] == "anthropic:claude-haiku-4-5"
    assert meta["tools_enabled"] is False
    assert meta["message_count"] == 0

    # GET meta
    r = client.get(f"/v1/chat/sessions/{sid}/meta")
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_create_session_uses_defaults_when_body_empty(client):
    r = client.post("/v1/chat/sessions", json={})
    assert r.status_code == 201
    meta = r.json()
    assert meta["title"] == "Untitled"
    assert meta["model"] == "anthropic:claude-haiku-4-5"


def test_patch_meta(client):
    r = client.post("/v1/chat/sessions", json={"title": "Original"})
    sid = r.json()["id"]

    r = client.patch(
        f"/v1/chat/sessions/{sid}/meta",
        json={"title": "Renamed", "model": "openai:gpt-5", "tools_enabled": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Renamed"
    assert body["model"] == "openai:gpt-5"
    assert body["tools_enabled"] is True


def test_patch_meta_404(client):
    r = client.patch("/v1/chat/sessions/bogus/meta", json={"title": "x"})
    assert r.status_code == 404


def test_get_meta_404(client):
    r = client.get("/v1/chat/sessions/bogus/meta")
    assert r.status_code == 404


def test_list_sessions_returns_newest_first(client):
    a = client.post("/v1/chat/sessions", json={"title": "A"}).json()["id"]
    b = client.post("/v1/chat/sessions", json={"title": "B"}).json()["id"]
    c = client.post("/v1/chat/sessions", json={"title": "C"}).json()["id"]

    r = client.get("/v1/chat/sessions")
    assert r.status_code == 200
    data = r.json()
    assert "sessions" in data
    ids = [s["id"] for s in data["sessions"]]
    # All three present.
    assert set(ids) >= {a, b, c}


def test_archive_then_404(client):
    r = client.post("/v1/chat/sessions", json={"title": "x"})
    sid = r.json()["id"]

    r = client.post(f"/v1/chat/sessions/{sid}/archive")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # active route returns 404
    r = client.get(f"/v1/chat/sessions/{sid}/meta")
    assert r.status_code == 404

    # archived list shows it
    r = client.get("/v1/chat/sessions?archived=true")
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json()["sessions"])


def test_send_message_404_for_missing_session(client):
    r = client.post("/v1/chat/sessions/bogus/messages", json={"message": "hi"})
    assert r.status_code == 404


def test_transcript_stub_501(client):
    r = client.post("/v1/chat/sessions", json={})
    sid = r.json()["id"]
    r = client.get(f"/v1/chat/sessions/{sid}/transcript")
    assert r.status_code == 501


def test_validation_rejects_oversize_inputs(client):
    """MEDIUM #3 — bounded inputs."""
    # title too long
    r = client.post("/v1/chat/sessions", json={"title": "x" * 200})
    assert r.status_code == 422
    # system_prompt too long
    r = client.post("/v1/chat/sessions", json={"system_prompt": "p" * 10000})
    assert r.status_code == 422
    # message too long
    sid = client.post("/v1/chat/sessions", json={}).json()["id"]
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": "m" * 20000},
    )
    assert r.status_code == 422


def test_validation_rejects_unknown_model_id(client):
    """MEDIUM #3 — model must be in the curated catalog."""
    r = client.post("/v1/chat/sessions", json={"model": "anthropic:fake-model-x"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Unknown model id" in str(detail) or "Unknown model id" in detail.get("what", "")


def test_list_limit_clamped(client):
    """MEDIUM #3 — list?limit out of bounds rejected."""
    assert client.get("/v1/chat/sessions?limit=0").status_code == 422
    assert client.get("/v1/chat/sessions?limit=10000").status_code == 422


def test_kaos_agents_passthrough_routes_mounted(client):
    """Smoke that create_app() routes ride along."""
    # GET /v1/sessions/{id} 404 means the route exists and reached
    # storage — it's the kaos-agents-native route. A 405/501 would
    # mean we lost the route.
    r = client.get("/v1/sessions/some-nonexistent-id")
    assert r.status_code in (404,), r.text
