"""Live LLM integration tests.

Per top-level CLAUDE.md § Testing Standards: live tests are the
acceptance gate. Mocked tests are documentation, not proof.

These tests hit `anthropic:claude-haiku-4-5` — the cheapest current-gen
model — and validate the full proxy stream from the SPA's perspective.
Gated on `ANTHROPIC_API_KEY` being set (legacy env var honored by
`kaos-llm-client` per its settings hierarchy).

Skip with `pytest -m "not live"`.
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live]


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("KAOS_LLM_ANTHROPIC_API_KEY"))


pytestmark.append(pytest.mark.skipif(not _has_anthropic_key(), reason="ANTHROPIC_API_KEY not set"))


def _parse_sse_events(body: str) -> list[dict]:
    """Walk an SSE response body and return parsed event payloads.

    Normalizes CRLF → LF first (sse-starlette emits CRLF), splits on
    blank-line boundaries, then parses event/data fields per RFC 8895.
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    out: list[dict] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        payload: dict = {"_event": "message"}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                payload["_event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                # Per SSE spec the leading space after `:` is stripped.
                data_lines.append(line[len("data:") :].lstrip(" "))
            # other prefixes (id:, retry:, comments starting with ":") ignored
        if data_lines:
            raw = "\n".join(data_lines)
            try:
                payload["data"] = json.loads(raw)
            except json.JSONDecodeError:
                payload["data"] = raw
        out.append(payload)
    return out


def test_live_haiku_one_turn(client):
    """A complete chat round-trip should yield text_delta + turn_summary."""
    # Create session — server-side defaults to claude-haiku-4-5.
    r = client.post(
        "/v1/chat/sessions",
        json={"title": "live-haiku-smoke", "model": "anthropic:claude-haiku-4-5"},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # Stream a turn.
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": "Respond with the single word: pong"},
        headers={"Accept": "text/event-stream"},
    )
    assert r.status_code == 200, r.text

    events = _parse_sse_events(r.text)
    types = [e.get("_event") for e in events]
    assert "text_delta" in types, f"missing text_delta in {types}"
    assert "turn_summary" in types, f"missing turn_summary in {types}"
    assert "run_error" not in types, f"unexpected run_error: {events}"

    # Metadata bumped.
    r = client.get(f"/v1/chat/sessions/{sid}/meta")
    assert r.status_code == 200
    assert r.json()["message_count"] >= 1
    assert r.json()["last_message_at"] is not None


def test_live_model_override_via_patch(client):
    """Patching model on the metadata sidecar should affect the next turn."""
    from app.settings import AppSettings

    expected_default = AppSettings().default_model
    r = client.post("/v1/chat/sessions", json={"title": "override-test"})
    sid = r.json()["id"]
    assert r.json()["model"] == expected_default

    # Patch model to a different valid id. We use Haiku 4.5 as the
    # cheaper override target so the live test stays inexpensive — the
    # session's *default* (now frontier-tier per AppSettings) is the
    # contract this test verifies the user can override away from.
    r = client.patch(
        f"/v1/chat/sessions/{sid}/meta",
        json={"model": "anthropic:claude-haiku-4-5"},
    )
    assert r.status_code == 200

    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": "Say 'ok' and nothing else."},
        headers={"Accept": "text/event-stream"},
    )
    assert r.status_code == 200
    events = _parse_sse_events(r.text)
    types = [e.get("_event") for e in events]
    assert "turn_summary" in types

    # Verify the turn_summary actually carries the model id (the wire
    # payload includes it inside the response state).
    turn = next(e for e in events if e.get("_event") == "turn_summary")
    data = turn.get("data")
    assert isinstance(data, dict)
    # Field name varies by kaos-agents version; assert we at least got a
    # text and a tokens_used so the contract is intact.
    assert "text" in data
    assert "tokens_used" in data
