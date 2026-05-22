"""Unit tests for the per-turn StateSnapshot writer (plan §Issue 5)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.services.state_snapshot import (
    SNAPSHOT_VERSION,
    build_snapshot_payload,
    turn_snapshot_path,
)


@dataclass
class _FakeRecord:
    """Minimal stand-in for ``ToolCallRecord`` — only the fields the
    snapshot writer cares about."""

    tool_name: str
    is_error: bool = False
    duration_ms: float | None = None
    cost_usd: float | None = None
    started_at: float | None = None


@pytest.mark.unit
def test_turn_snapshot_path_uses_runs_directory() -> None:
    """Snapshots live alongside the per-turn sidecar so an auditor
    finds both in the same place."""
    assert turn_snapshot_path("01KSTEST", 0) == "runs/turn-0000/snapshot.json"
    assert turn_snapshot_path("01KSTEST", 42) == "runs/turn-0042/snapshot.json"
    assert turn_snapshot_path("01KSTEST", 9999) == "runs/turn-9999/snapshot.json"


@pytest.mark.unit
def test_snapshot_payload_required_fields_present() -> None:
    """The schema is load-bearing for the replay tool — pin the set
    of top-level keys here."""
    payload = build_snapshot_payload(
        session_id="01KSTEST",
        turn_index=0,
        run_id="turn-0000-abc123",
        model="anthropic:claude-sonnet-4-6",
        tenant_id="t-1",
        build_sha="6b1e2402983c",
        sidecar_records=[],
        turn_cost_usd=0.0,
        turn_tokens=0,
    )
    assert payload["snapshot_version"] == SNAPSHOT_VERSION
    assert payload["session_id"] == "01KSTEST"
    assert payload["turn_index"] == 0
    assert payload["run_id"] == "turn-0000-abc123"
    assert payload["model"] == "anthropic:claude-sonnet-4-6"
    assert payload["tenant_id"] == "t-1"
    assert payload["build_sha"] == "6b1e2402983c"
    assert payload["tool_calls"] == []
    assert "captured_at" in payload
    assert payload["totals"] == {
        "cost_usd": 0.0,
        "tokens": 0,
        "tool_call_count": 0,
        "tool_error_count": 0,
    }


@pytest.mark.unit
def test_snapshot_payload_serialises_tool_call_records() -> None:
    """Each ToolCallRecord becomes a structured tool_calls[] entry."""
    payload = build_snapshot_payload(
        session_id="01KSTEST",
        turn_index=3,
        run_id="turn-0003-xyz789",
        model="openai:gpt-5.4-mini",
        tenant_id=None,
        build_sha=None,
        sidecar_records=[
            _FakeRecord("kaos-content-search-document", duration_ms=250.5, cost_usd=0.0012),
            _FakeRecord("kaos-source-fetch-url", is_error=True, duration_ms=15000.0),
            _FakeRecord("kaos-office-parse-docx", duration_ms=480.3, cost_usd=0.0),
        ],
        turn_cost_usd=0.045,
        turn_tokens=12_345,
    )
    assert len(payload["tool_calls"]) == 3
    assert payload["tool_calls"][0]["tool_name"] == "kaos-content-search-document"
    assert payload["tool_calls"][0]["duration_ms"] == 250.5
    assert payload["tool_calls"][0]["cost_usd"] == 0.0012
    assert payload["tool_calls"][1]["is_error"] is True
    assert payload["tool_calls"][2]["tool_name"] == "kaos-office-parse-docx"
    assert payload["totals"]["cost_usd"] == 0.045
    assert payload["totals"]["tokens"] == 12_345
    assert payload["totals"]["tool_call_count"] == 3
    assert payload["totals"]["tool_error_count"] == 1


@pytest.mark.unit
def test_snapshot_payload_handles_missing_optional_fields() -> None:
    """Pre-existing ToolCallRecord shapes may not carry duration_ms /
    cost_usd / started_at. The writer drops the field rather than
    emitting None — keeps the JSON tight."""
    payload = build_snapshot_payload(
        session_id="01KSTEST",
        turn_index=0,
        run_id="turn-0000-abc",
        model="openai:gpt-5.4-mini",
        tenant_id=None,
        build_sha=None,
        sidecar_records=[_FakeRecord("kaos-content-search-document")],
        turn_cost_usd=0.0,
        turn_tokens=0,
    )
    rec = payload["tool_calls"][0]
    assert rec["tool_name"] == "kaos-content-search-document"
    assert rec["is_error"] is False
    assert "duration_ms" not in rec
    assert "cost_usd" not in rec
    assert "started_at" not in rec


@pytest.mark.unit
def test_snapshot_payload_round_trips_through_json() -> None:
    """The wire format MUST survive a json.dumps + json.loads round-
    trip. ``captured_at`` is ISO-8601 (string), ``cost_usd`` is float,
    no datetime objects or other non-JSON types leak in."""
    payload = build_snapshot_payload(
        session_id="01KSTEST",
        turn_index=7,
        run_id="turn-0007-feed42",
        model="anthropic:claude-sonnet-4-6",
        tenant_id="t-1",
        build_sha="abc123",
        sidecar_records=[_FakeRecord("kaos-pdf-extract-text", duration_ms=99.9)],
        turn_cost_usd=0.005,
        turn_tokens=500,
    )
    blob = json.dumps(payload)
    reloaded = json.loads(blob)
    assert reloaded == payload


@pytest.mark.unit
def test_snapshot_error_count_only_counts_errored_records() -> None:
    """``tool_error_count`` should equal the number of records with
    ``is_error=True``, not the total call count."""
    payload = build_snapshot_payload(
        session_id="01KSTEST",
        turn_index=0,
        run_id="turn-0000-aaa",
        model="anthropic:claude-sonnet-4-6",
        tenant_id=None,
        build_sha=None,
        sidecar_records=[
            _FakeRecord("a"),
            _FakeRecord("b", is_error=True),
            _FakeRecord("c", is_error=True),
            _FakeRecord("d"),
        ],
        turn_cost_usd=0.0,
        turn_tokens=0,
    )
    assert payload["totals"]["tool_call_count"] == 4
    assert payload["totals"]["tool_error_count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_turn_snapshot_returns_none_when_runtime_missing() -> None:
    """Test stubs sometimes pass ``runtime=None``; the writer must
    short-circuit cleanly instead of crashing."""
    from app.services.state_snapshot import write_turn_snapshot

    result = await write_turn_snapshot(
        runtime=None,
        session_id="01KSTEST",
        turn_index=0,
        run_id="turn-0000-aaa",
        model="anthropic:claude-sonnet-4-6",
        tenant_id=None,
        build_sha=None,
        sidecar_records=[],
        turn_cost_usd=0.0,
        turn_tokens=0,
    )
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_turn_snapshot_writes_through_runtime_vfs() -> None:
    """Happy path: the writer calls ``runtime.vfs.write(path, blob)``
    with the canonical path and a JSON-serialised payload."""
    from app.services.state_snapshot import write_turn_snapshot

    writes: list[tuple[str, bytes]] = []

    class _FakeVFS:
        async def write(self, path: str, blob: bytes) -> None:
            writes.append((path, blob))

    class _FakeRuntime:
        vfs = _FakeVFS()

    result = await write_turn_snapshot(
        runtime=_FakeRuntime(),
        session_id="01KSTEST",
        turn_index=5,
        run_id="turn-0005-cafe",
        model="openai:gpt-5.4-mini",
        tenant_id=None,
        build_sha="6b1e",
        sidecar_records=[_FakeRecord("kaos-content-search-document")],
        turn_cost_usd=0.01,
        turn_tokens=200,
    )

    assert result == "runs/turn-0005/snapshot.json"
    assert len(writes) == 1
    path, blob = writes[0]
    assert path == "runs/turn-0005/snapshot.json"
    decoded = json.loads(blob.decode("utf-8"))
    assert decoded["session_id"] == "01KSTEST"
    assert decoded["turn_index"] == 5
    assert decoded["run_id"] == "turn-0005-cafe"
    assert decoded["totals"]["tool_call_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_turn_snapshot_swallows_vfs_failures() -> None:
    """A VFS write failure must NOT raise — best-effort is the
    contract per the docstring."""
    from app.services.state_snapshot import write_turn_snapshot

    class _ExplodingVFS:
        async def write(self, path: str, blob: bytes) -> None:
            raise RuntimeError("disk full")

    class _BrokenRuntime:
        vfs = _ExplodingVFS()

    result = await write_turn_snapshot(
        runtime=_BrokenRuntime(),
        session_id="01KSTEST",
        turn_index=0,
        run_id="turn-0000-aaa",
        model="anthropic:claude-sonnet-4-6",
        tenant_id=None,
        build_sha=None,
        sidecar_records=[],
        turn_cost_usd=0.0,
        turn_tokens=0,
    )
    assert result is None
