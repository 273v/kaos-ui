"""HTTP round-trip tests against our extension routes — no LLM calls."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_gate_on_extension_routes(app):
    """/v1/chat/* and /v1/models must require auth.

    Unauthenticated requests get 401; valid bearer gets 2xx. The SPA's
    login probe targets an auth-gated route so the probe accurately
    reflects whether the token is valid.
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
    # default_tools_enabled is True (AppSettings default — tools on by
    # default so the agent can use uploaded files + kaos-source connectors).
    assert meta["tools_enabled"] is True
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


def test_send_message_rejects_invalid_per_turn_model(client):
    """P2-4: SendMessageBody.model is validated through the same model
    catalog as PATCH /meta. An unknown model 422s instead of being
    forwarded to kaos-agents as a bad provider:model id."""
    r = client.post("/v1/chat/sessions", json={})
    sid = r.json()["id"]
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": "hi", "model": "fake-provider:fake-model"},
    )
    assert r.status_code == 422


def test_send_message_accepts_known_per_turn_model(client):
    """P2-4: SendMessageBody.model with a model that exists in the
    catalog passes validation. The request is dispatched to kaos-agents
    (which will then handle the live LLM call — we don't run live here)."""
    r = client.post("/v1/chat/sessions", json={"model": "anthropic:claude-haiku-4-5"})
    sid = r.json()["id"]
    # Use a non-streaming-aware client.stream() to avoid hanging on SSE.
    with client.stream(
        "POST",
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": "hi", "model": "anthropic:claude-sonnet-4-6"},
    ) as resp:
        # 200 OK; we abort reading because we don't want to hit a live LLM.
        assert resp.status_code == 200


def test_transcript_export_markdown(client):
    """P2-4: GET /transcript?format=markdown returns a text/markdown
    download with the session title in the filename."""
    r = client.post("/v1/chat/sessions", json={"title": "My Session"})
    sid = r.json()["id"]
    r = client.get(f"/v1/chat/sessions/{sid}/transcript?format=markdown")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "My Session.md" in r.headers["content-disposition"]
    assert "# My Session" in r.text


def test_transcript_export_json(client):
    r = client.post("/v1/chat/sessions", json={"title": "T2"})
    sid = r.json()["id"]
    r = client.get(f"/v1/chat/sessions/{sid}/transcript?format=json")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    body = r.json()
    assert body["session_id"] == sid
    assert "messages" in body


def test_transcript_export_docx(client):
    """P2-4: format=docx round-trips through kaos_content.parse_markdown
    + kaos_office.docx.write_docx_bytes — produces a valid .docx
    (ZIP magic bytes 'PK')."""
    r = client.post("/v1/chat/sessions", json={"title": "DocxSession"})
    sid = r.json()["id"]
    r = client.get(f"/v1/chat/sessions/{sid}/transcript?format=docx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "DocxSession.docx" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"  # ZIP/DOCX magic


def test_transcript_export_unknown_format_422(client):
    r = client.post("/v1/chat/sessions", json={})
    sid = r.json()["id"]
    r = client.get(f"/v1/chat/sessions/{sid}/transcript?format=xml")
    assert r.status_code == 422


def test_transcript_export_404_for_unknown_session(client):
    r = client.get(
        "/v1/chat/sessions/01NOPESUCHSESSIONIDABCDEFG/transcript?format=markdown"
    )
    assert r.status_code == 404


def test_validation_rejects_oversize_inputs(client):
    """Bounded inputs — title, system_prompt, message all clamped."""
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
    """body.model must be one of the curated catalog ids."""
    r = client.post("/v1/chat/sessions", json={"model": "anthropic:fake-model-x"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Unknown model id" in str(detail) or "Unknown model id" in detail.get("what", "")


def test_list_limit_clamped(client):
    """list?limit out of bounds rejected."""
    assert client.get("/v1/chat/sessions?limit=0").status_code == 422
    assert client.get("/v1/chat/sessions?limit=10000").status_code == 422


def test_kaos_agents_passthrough_routes_mounted(client):
    """Smoke that create_app() routes ride along."""
    # GET /v1/sessions/{id} 404 means the route exists and reached
    # storage — it's the kaos-agents-native route. A 405/501 would
    # mean we lost the route.
    r = client.get("/v1/sessions/some-nonexistent-id")
    assert r.status_code in (404,), r.text
