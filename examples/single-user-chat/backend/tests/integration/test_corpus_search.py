"""P2-3 — corpus-search route happy path + edge cases.

Mocks the search service rather than driving real PDF parsing, so the
test stays fast + dep-free. End-to-end behavior (PDF -> AST ->
indexed) is covered by manual smoke when wiring is changed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.services.corpus_search import CorpusSearchHit

pytestmark = pytest.mark.integration


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5"},
    )
    return response.json()["id"]


def test_search_corpus_returns_hits(client: TestClient) -> None:
    sid = _create_session(client)
    fake_hits = [
        CorpusSearchHit(
            filename="contract.pdf",
            score=4.2,
            snippet="The termination clause requires 60 days notice.",
            char_offset=1024,
        ),
        CorpusSearchHit(
            filename="contract.pdf",
            score=2.1,
            snippet="Severance pay is calculated...",
            char_offset=2048,
        ),
    ]
    with patch(
        "app.services.corpus_search.search_session_corpus",
        return_value=fake_hits,
    ):
        resp = client.get(f"/v1/chat/sessions/{sid}/files/search?q=termination")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["query"] == "termination"
    assert body["hits"][0]["filename"] == "contract.pdf"
    assert body["hits"][0]["score"] == 4.2
    assert "termination" in body["hits"][0]["snippet"].lower()


def test_search_corpus_empty_query_returns_zero_hits(client: TestClient) -> None:
    sid = _create_session(client)
    with patch(
        "app.services.corpus_search.search_session_corpus",
        return_value=[],
    ):
        resp = client.get(f"/v1/chat/sessions/{sid}/files/search?q=")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_search_corpus_404_for_unknown_session(client: TestClient) -> None:
    resp = client.get("/v1/chat/sessions/01NOPESUCHSESSIONIDABCDEFGH/files/search?q=foo")
    assert resp.status_code == 404


def test_search_corpus_clamps_top_k(client: TestClient) -> None:
    """top_k > 50 must be clamped to 50; <=0 must be clamped to 1.

    Defensive — keeps the underlying BM25 index from doing pathological
    work on a malicious request.
    """
    sid = _create_session(client)
    captured = {}

    async def _spy(*, runtime, session_id, query, top_k):
        captured["top_k"] = top_k
        return []

    with patch("app.services.corpus_search.search_session_corpus", new=_spy):
        client.get(f"/v1/chat/sessions/{sid}/files/search?q=x&top_k=9999")
    assert captured["top_k"] == 50

    with patch("app.services.corpus_search.search_session_corpus", new=_spy):
        client.get(f"/v1/chat/sessions/{sid}/files/search?q=x&top_k=0")
    assert captured["top_k"] == 1


def test_search_corpus_requires_auth() -> None:
    from fastapi.testclient import TestClient as _TC

    from app.main import app

    bare = _TC(app)
    response = bare.get("/v1/chat/sessions/01J/files/search?q=foo")
    assert response.status_code in (401, 403)
