"""Integration tests for POST /v1/chat/sessions/{id}/citations (P2-1).

Verifies the SPA-facing post-turn citation extraction endpoint:

- auth: rejects requests without a bearer token
- 404 for unknown sessions
- happy path: returns a non-empty `citations` list with `kind` /
  `normalized` fields for a string containing a real CFR + case cite
- 422 on empty body
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_citations_requires_auth(app) -> None:
    """No bearer → 401."""
    unauth = TestClient(app)
    r = unauth.post("/v1/chat/sessions/whatever/citations", json={"text": "irrelevant"})
    assert r.status_code == 401


def test_citations_404_for_unknown_session(client: TestClient) -> None:
    r = client.post(
        "/v1/chat/sessions/missing/citations",
        json={"text": "See 17 CFR 240.10b-5."},
    )
    assert r.status_code == 404


def test_citations_happy_path_extracts_typed_records(client: TestClient) -> None:
    """A real CFR + case string yields ≥ 2 citations with proper kinds."""
    r = client.post("/v1/chat/sessions", json={})
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]

    body = {
        "text": (
            "Under Rule 10b-5 of the federal securities laws (17 CFR 240.10b-5), "
            "as construed in Brown v. Board of Education, 347 U.S. 483 (1954), "
            "the defendant's conduct may be actionable."
        ),
    }
    r = client.post(f"/v1/chat/sessions/{sid}/citations", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["session_id"] == sid
    assert payload["count"] >= 2, payload
    kinds = {c["kind"] for c in payload["citations"]}
    # CFR + case must both be detected; the kaos-citations 0.1.0a2
    # contract guarantees both kinds appear for this input.
    assert "cfr" in kinds, kinds
    assert "case" in kinds, kinds
    # Every citation has the documented required fields.
    for c in payload["citations"]:
        assert isinstance(c.get("raw"), str) and c["raw"]
        assert isinstance(c.get("normalized"), str)
        assert isinstance(c.get("kind"), str)


def test_citations_422_on_empty_text(client: TestClient) -> None:
    r = client.post("/v1/chat/sessions", json={})
    sid = r.json()["id"]
    r = client.post(f"/v1/chat/sessions/{sid}/citations", json={"text": ""})
    assert r.status_code == 422
