"""Integration tests for `tool_calls` hydration on GET /v1/chat/sessions/{id}/messages.

The chat router writes a per-turn sidecar
``sessions/{id}/toolcalls/turn-{N:04d}.jsonl`` while the SSE stream
runs, then ``get_history`` reads each sidecar and attaches the rows
to the matching assistant message. These tests pre-seed sidecars
directly in the VFS to verify the read path without spinning up the
LLM-dependent stream.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.tool_call_recorder import (
    ToolCallRecord,
    serialize_records,
    turn_sidecar_path,
)


def _create_session(client: TestClient, **body) -> str:
    r = client.post("/v1/chat/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_history_returns_empty_tool_calls_for_pre_existing_session(
    client: TestClient,
) -> None:
    """A session with no sidecars at all returns an empty list (not 500)."""
    sid = _create_session(client)
    r = client.get(f"/v1/chat/sessions/{sid}/messages")
    assert r.status_code == 200, r.text
    body = r.json()
    # kaos-agents has no memory for a fresh session, so messages is empty.
    # The key property here: the route DOES NOT error trying to read
    # missing sidecars.
    assert body["messages"] == []


async def test_history_sidecar_roundtrip(client: TestClient, app) -> None:
    """When a turn-0000.jsonl sidecar exists, the recorder's serialization
    round-trips through the runtime VFS and parses back to the same rows.

    We can't easily inject a real assistant message into kaos-agents
    memory without the LLM, so this test pins the LOWER-LEVEL invariant
    that the get_history hydration path depends on: serialize_records →
    runtime.vfs.write → runtime.vfs.read → parse_records_jsonl is an
    identity over the ToolCallRecord shape. A future change that breaks
    the JSONL contract (or the path scheme) lights this up immediately.
    """
    sid = _create_session(client)
    runtime = app.state.kaos_runtime

    records = [
        ToolCallRecord(
            id="call-1",
            name="kaos-source-fr-search",
            status="done",
            args_preview='{"q": "cheese"}',
            result_preview='[{"document_number": "2026-12345"}]',
        ),
        ToolCallRecord(
            id="call-2",
            name="kaos-pdf-extract-parse",
            status="error",
            result_preview="PDF parser raised",
        ),
    ]

    path = turn_sidecar_path(sid, 0)
    await runtime.vfs.write(path, serialize_records(records))

    from app.services.tool_call_recorder import parse_records_jsonl

    blob = await runtime.vfs.read(path)
    parsed = parse_records_jsonl(blob)
    assert [r.id for r in parsed] == ["call-1", "call-2"]
    assert parsed[0].name == "kaos-source-fr-search"
    assert parsed[1].status == "error"


def test_sidecar_path_uses_zero_padded_turn_index() -> None:
    """Pinned contract — `chat.py` get_history relies on this exact format
    to find sidecars after they're written by the chat stream."""
    assert turn_sidecar_path("01HX", 0) == "sessions/01HX/toolcalls/turn-0000.jsonl"
    assert turn_sidecar_path("01HX", 7) == "sessions/01HX/toolcalls/turn-0007.jsonl"


def test_history_endpoint_404s_for_unknown_session(client: TestClient) -> None:
    r = client.get("/v1/chat/sessions/never-existed/messages")
    assert r.status_code == 404
