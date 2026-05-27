"""Unit tests for the message-level feedback endpoint (Issue 10 L2).

The endpoint must:

1. Append one JSONL line per call, never overwrite.
2. Reject non-existent sessions with 404.
3. Reject ``value`` outside ``{"up","down"}`` with 422.
4. Reject ``note`` longer than 2000 chars (Pydantic max_length).
5. Stamp the server-side ``submitted_at`` (clients can't forge audit time).
6. Survive concurrent writes from two clients without interleave
   (relies on POSIX O_APPEND atomicity for sub-PIPE_BUF writes).

No live LLM calls. Uses TestClient against the real backend app
factory so the routes wire through the full FastAPI stack.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_AUTH = "Bearer demo-token-must-be-at-least-32-chars-long-for-validation"


def _make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    """Build a fresh app rooted at tmp_path/.kaos-vfs + create one
    session. Returns the TestClient and the new session id.
    """
    monkeypatch.setenv("APP_VFS_PATH", str(tmp_path / ".kaos-vfs"))
    monkeypatch.setenv(
        "KAOS_AGENTS_API_API_TOKEN",
        "demo-token-must-be-at-least-32-chars-long-for-validation",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-stub-for-health")

    import app.logging_setup as ls

    ls._CONFIGURED = False  # type: ignore[attr-defined]

    import sys

    for mod in list(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]

    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/v1/chat/sessions",
        headers={"Authorization": _AUTH},
        json={"title": "feedback-endpoint test"},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    return client, sid


@pytest.mark.unit
def test_feedback_up_appends_one_jsonl_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sid = _make_app(tmp_path, monkeypatch)
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/msg-1/feedback",
        headers={"Authorization": _AUTH},
        json={"value": "up"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert "submitted_at" in body

    log_path = tmp_path / ".kaos-vfs" / "single-user-chat" / "sessions" / sid / "feedback.jsonl"
    assert log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["session_id"] == sid
    assert lines[0]["message_id"] == "msg-1"
    assert lines[0]["value"] == "up"
    assert lines[0]["note"] is None
    assert "submitted_at" in lines[0]


@pytest.mark.unit
def test_feedback_down_with_note_persists_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sid = _make_app(tmp_path, monkeypatch)
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/msg-2/feedback",
        headers={"Authorization": _AUTH},
        json={"value": "down", "note": "answer cited training memory, not the corpus"},
    )
    assert r.status_code == 202, r.text
    log_path = tmp_path / ".kaos-vfs" / "single-user-chat" / "sessions" / sid / "feedback.jsonl"
    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["value"] == "down"
    assert record["note"] == "answer cited training memory, not the corpus"


@pytest.mark.unit
def test_repeated_feedback_appends_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User changes their mind: thumbs-up, then thumbs-down on the
    same message. Both records must survive in the JSONL — auditors
    care about the timeline, not just the latest sentiment.
    """
    client, sid = _make_app(tmp_path, monkeypatch)
    for value in ("up", "down", "up"):
        r = client.post(
            f"/v1/chat/sessions/{sid}/messages/msg-3/feedback",
            headers={"Authorization": _AUTH},
            json={"value": value},
        )
        assert r.status_code == 202
    log_path = tmp_path / ".kaos-vfs" / "single-user-chat" / "sessions" / sid / "feedback.jsonl"
    lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert [r["value"] for r in lines] == ["up", "down", "up"]


@pytest.mark.unit
def test_feedback_rejects_unknown_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, sid = _make_app(tmp_path, monkeypatch)
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/msg-4/feedback",
        headers={"Authorization": _AUTH},
        json={"value": "meh"},
    )
    # Pydantic Literal rejection → 422
    assert r.status_code == 422, r.text


@pytest.mark.unit
def test_feedback_rejects_note_over_2k_chars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sid = _make_app(tmp_path, monkeypatch)
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/msg-5/feedback",
        headers={"Authorization": _AUTH},
        json={"value": "down", "note": "x" * 2001},
    )
    assert r.status_code == 422


@pytest.mark.unit
def test_feedback_unknown_session_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _make_app(tmp_path, monkeypatch)
    r = client.post(
        "/v1/chat/sessions/01NEVERPERSISTED0000000/messages/msg-6/feedback",
        headers={"Authorization": _AUTH},
        json={"value": "up"},
    )
    assert r.status_code == 404
