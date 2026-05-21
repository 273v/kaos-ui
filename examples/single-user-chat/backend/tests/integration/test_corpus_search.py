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

    async def _spy(*, runtime, session_id, query, top_k, tenant_id=None):
        # tenant_id added by R0.2 / B0.1 — accept it so the spy
        # matches the production signature.
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


def test_search_corpus_surfaces_citation_grounding_fields(client: TestClient) -> None:
    """B0.6 — ``CorpusSearchHitWire`` carries block_ref / page /
    section_title / path so the SPA can render anchored citations.

    Pre-fix, the wire DTO dropped these four kaos-content
    ``SearchResult`` fields and the agent had to either fabricate a
    citation or refuse — citation-fabrication-via-omission. Post-fix
    every hit ships the structural breadcrumb (or explicit nulls so
    the agent knows it must NOT invent one).
    """
    sid = _create_session(client)
    fake_hits = [
        CorpusSearchHit(
            filename="nda.docx",
            score=5.7,
            snippet="The receiving party shall hold information in confidence...",
            char_offset=512,
            block_ref="#/body/14",
            page=3,
            section_title="Section 3.4. Confidentiality.",
            path=("ARTICLE III", "Section 3.4. Confidentiality."),
        ),
        CorpusSearchHit(
            # Empty path → contract says "agent must NOT invent a
            # citation for this hit." We still surface the hit; the
            # agent's job is to refuse to cite a section number.
            filename="memo.pdf",
            score=3.1,
            snippet="A bare paragraph with no enclosing heading...",
            char_offset=2048,
        ),
    ]
    with patch(
        "app.services.corpus_search.search_session_corpus",
        return_value=fake_hits,
    ):
        resp = client.get(f"/v1/chat/sessions/{sid}/files/search?q=confidence")

    assert resp.status_code == 200
    hits = resp.json()["hits"]
    assert len(hits) == 2

    # First hit — fully grounded.
    grounded = hits[0]
    assert grounded["block_ref"] == "#/body/14"
    assert grounded["page"] == 3
    assert grounded["section_title"] == "Section 3.4. Confidentiality."
    assert grounded["path"] == ["ARTICLE III", "Section 3.4. Confidentiality."]

    # Second hit — no structural breadcrumb; defaults preserve the
    # "no citation available" signal.
    ungrounded = hits[1]
    assert ungrounded["block_ref"] is None
    assert ungrounded["page"] is None
    assert ungrounded["section_title"] is None
    assert ungrounded["path"] == []


def test_corpus_search_hit_defaults_are_safe_for_legacy_callers() -> None:
    """``CorpusSearchHit`` constructed without B0.6 fields still works
    — the dataclass defaults must keep the older mocked-test pattern
    backward compatible (see ``test_search_corpus_returns_hits`` for
    the baseline shape)."""
    legacy = CorpusSearchHit(
        filename="x.pdf",
        score=1.0,
        snippet="hello",
        char_offset=0,
    )
    assert legacy.block_ref is None
    assert legacy.page is None
    assert legacy.section_title is None
    assert legacy.path == ()
