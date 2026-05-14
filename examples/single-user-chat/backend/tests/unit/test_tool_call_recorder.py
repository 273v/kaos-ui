"""Unit tests for the SSE tool-call recorder.

The recorder is a pure tap — given SSE event payloads, it accumulates
ToolCallRecord rows that the chat router persists as a per-turn VFS
sidecar. These tests pin the wire-shape mapping so a future kaos-agents
event-payload tweak surfaces as a test failure rather than silent loss
of history data.
"""

from __future__ import annotations

from app.services.tool_call_recorder import (
    TurnToolCallRecorder,
    parse_records_jsonl,
    serialize_records,
    turn_sidecar_path,
)


def _start_event(call_id: str, tool_name: str = "kaos-pdf-extract-parse") -> dict:
    return {
        "type": "span",
        "subject": "tool_call",
        "phase": "start",
        "span_id": "s0",
        "parent_span_id": None,
        "attributes": {"call_id": call_id, "tool_name": tool_name},
    }


def _complete_event(
    call_id: str,
    tool_name: str = "kaos-pdf-extract-parse",
    result: str = '{"pages": 3}',
    is_error: bool = False,
) -> dict:
    return {
        "type": "span",
        "subject": "tool_call",
        "phase": "complete",
        "span_id": "s0",
        "parent_span_id": None,
        "attributes": {
            "call_id": call_id,
            "tool_name": tool_name,
            "result_summary": result,
            "is_error": is_error,
        },
    }


def _args_delta_event(call_id: str, delta: str, tool_name: str | None = None) -> dict:
    return {
        "type": "tool_call_args_delta",
        "tool_name": tool_name,
        "call_id": call_id,
        "delta": delta,
    }


def test_start_then_complete_records_done() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("span", _start_event("c1"))
    rec.observe("span", _complete_event("c1"))
    rows = rec.records()
    assert len(rows) == 1
    assert rows[0].id == "c1"
    assert rows[0].name == "kaos-pdf-extract-parse"
    assert rows[0].status == "done"
    assert rows[0].result_preview == '{"pages": 3}'


def test_complete_without_start_still_records() -> None:
    """kaos-agents can drop the start event for cached tools; the recorder
    treats `complete` as the source of truth."""
    rec = TurnToolCallRecorder()
    rec.observe("span", _complete_event("c2", tool_name="kaos-source-fr-search"))
    rows = rec.records()
    assert len(rows) == 1
    assert rows[0].name == "kaos-source-fr-search"
    assert rows[0].status == "done"


def test_error_complete_records_error_status() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("span", _start_event("c3"))
    rec.observe("span", _complete_event("c3", result="bad json", is_error=True))
    rows = rec.records()
    assert rows[0].status == "error"
    assert rows[0].result_preview == "bad json"


def test_args_delta_accumulates_into_args_preview() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("span", _start_event("c4", tool_name="kaos-source-fetch-url"))
    rec.observe("tool_call_args_delta", _args_delta_event("c4", '{"url":'))
    rec.observe("tool_call_args_delta", _args_delta_event("c4", '"https://example.com"}'))
    rec.observe("span", _complete_event("c4", tool_name="kaos-source-fetch-url"))
    rows = rec.records()
    assert rows[0].args_preview == '{"url":"https://example.com"}'
    assert rows[0].status == "done"


def test_multiple_calls_preserved_in_arrival_order() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("span", _start_event("first"))
    rec.observe("span", _start_event("second", tool_name="kaos-citations-extract"))
    rec.observe("span", _complete_event("second", tool_name="kaos-citations-extract", result="[c0001]"))
    rec.observe("span", _complete_event("first"))
    rows = rec.records()
    assert [r.id for r in rows] == ["first", "second"]


def test_non_tool_events_are_ignored() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("text_delta", {"type": "text_delta", "content": "hi"})
    rec.observe("span", {"type": "span", "subject": "turn", "phase": "start"})
    rec.observe("usage_observed", {"type": "usage_observed", "total_tokens": 100})
    assert rec.is_empty()


def test_args_delta_is_bounded() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("tool_call_args_delta", _args_delta_event("c5", "a" * 2000, tool_name="t"))
    rows = rec.records()
    assert rows[0].args_preview is not None
    assert len(rows[0].args_preview) <= 512


def test_serialize_then_parse_round_trips() -> None:
    rec = TurnToolCallRecorder()
    rec.observe("span", _start_event("a"))
    rec.observe("span", _complete_event("a", result="ok"))
    rec.observe("span", _start_event("b", tool_name="kaos-source-fr-search"))
    rec.observe("span", _complete_event("b", tool_name="kaos-source-fr-search", result="3 results"))
    blob = serialize_records(rec.records())
    parsed = parse_records_jsonl(blob)
    assert [r.id for r in parsed] == ["a", "b"]
    assert parsed[1].name == "kaos-source-fr-search"


def test_parse_jsonl_skips_malformed_lines() -> None:
    blob = b'{"id":"a","name":"t","status":"done"}\nnot-json\n{"id":"b","name":"t","status":"done"}\n'
    parsed = parse_records_jsonl(blob)
    assert [r.id for r in parsed] == ["a", "b"]


def test_turn_sidecar_path_is_zero_padded() -> None:
    assert turn_sidecar_path("S1", 0) == "sessions/S1/toolcalls/turn-0000.jsonl"
    assert turn_sidecar_path("S1", 42) == "sessions/S1/toolcalls/turn-0042.jsonl"
    assert turn_sidecar_path("S1", 12345) == "sessions/S1/toolcalls/turn-12345.jsonl"
