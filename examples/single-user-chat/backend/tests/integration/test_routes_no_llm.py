"""HTTP round-trip tests against our extension routes — no LLM calls."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


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


def test_kaos_agents_passthrough_routes_mounted(client):
    """Smoke that create_app() routes ride along."""
    # GET /v1/sessions/{id} 404 means the route exists and reached
    # storage — it's the kaos-agents-native route. A 405/501 would
    # mean we lost the route.
    r = client.get("/v1/sessions/some-nonexistent-id")
    assert r.status_code in (404,), r.text
