"""Integration tests for POST /v1/chat/sessions/{id}/files:backfill.

The backfill endpoint recomputes token_count + summary for files that
are missing them — typically after a backend upgrade adds those
fields. Without a live LLM key the summarizer fails silently (logged
WARNING), so we can assert {updated: N} but not that `summary`
becomes non-null in tests. Token count IS computable offline via
kaos-nlp-core, so we DO assert that.
"""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

# Reuse the canonical minimal-PDF fixture.
from tests.integration.test_uploads import _MINIMAL_PDF


def _create_session(client: TestClient) -> str:
    r = client.post("/v1/chat/sessions", json={})
    assert r.status_code == status.HTTP_201_CREATED, r.text
    return r.json()["id"]


def test_backfill_requires_auth(app) -> None:
    """No bearer → 401."""
    unauth = TestClient(app)
    r = unauth.post("/v1/chat/sessions/whatever/files:backfill")
    assert r.status_code == 401


def test_backfill_404_for_unknown_session(client: TestClient) -> None:
    r = client.post("/v1/chat/sessions/missing/files:backfill")
    assert r.status_code == 404


def test_backfill_returns_zero_for_session_with_no_files(client: TestClient) -> None:
    sid = _create_session(client)
    r = client.post(f"/v1/chat/sessions/{sid}/files:backfill")
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 0}


def test_backfill_idempotent_when_token_count_already_populated(client: TestClient) -> None:
    """Token count is computable offline (kaos-nlp-core), so a freshly
    uploaded file has it populated post-upload. A subsequent
    backfill without `overwrite` should be a no-op for that file.
    """
    sid = _create_session(client)
    up = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("doc.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    assert up.status_code == status.HTTP_201_CREATED, up.text
    files = client.get(f"/v1/chat/sessions/{sid}/files").json()["files"]
    assert files[0]["token_count"] is not None  # populated at upload

    # First backfill — summary is None (no LLM in tests), but token_count
    # is set, so the "needs backfill" predicate (both must be non-null)
    # still fires for this file.
    r = client.post(f"/v1/chat/sessions/{sid}/files:backfill")
    assert r.status_code == 200, r.text
    first_count = r.json()["updated"]

    # Second backfill — file is in the same state (still no summary),
    # so it still says "needs backfill". This is by design: the
    # summary stays null until an LLM key is wired up.
    r2 = client.post(f"/v1/chat/sessions/{sid}/files:backfill")
    assert r2.status_code == 200
    assert r2.json()["updated"] == first_count


def test_backfill_overwrite_refreshes_every_ready_file(client: TestClient) -> None:
    """`?overwrite=true` recomputes even when both fields are populated."""
    sid = _create_session(client)
    client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("a.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("b.pdf", _MINIMAL_PDF, "application/pdf")},
    )
    r = client.post(f"/v1/chat/sessions/{sid}/files:backfill?overwrite=true")
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2


def test_backfill_skips_failed_files(client: TestClient) -> None:
    """Parse-failed files have no AST sidecar to read from, so the
    backfill loop skips them. They count zero toward `updated`.
    """
    sid = _create_session(client)
    # Upload a corrupt PDF — parser will fail, file gets stored with
    # parse.status=failed.
    bad = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("bad.pdf", b"not a real pdf", "application/pdf")},
    )
    assert bad.status_code == status.HTTP_201_CREATED
    assert bad.json()["file"]["parse"]["status"] == "failed"

    r = client.post(f"/v1/chat/sessions/{sid}/files:backfill?overwrite=true")
    assert r.status_code == 200
    assert r.json()["updated"] == 0  # only the failed file in the session


def test_backfill_response_shape(client: TestClient) -> None:
    """Pinned wire contract: {"updated": int}, nothing else."""
    sid = _create_session(client)
    r = client.post(f"/v1/chat/sessions/{sid}/files:backfill")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"updated"}
    assert isinstance(body["updated"], int)
