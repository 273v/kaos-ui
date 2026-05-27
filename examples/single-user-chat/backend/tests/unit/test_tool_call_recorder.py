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
    rec.observe(
        "span", _complete_event("second", tool_name="kaos-citations-extract", result="[c0001]")
    )
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
    blob = (
        b'{"id":"a","name":"t","status":"done"}\nnot-json\n{"id":"b","name":"t","status":"done"}\n'
    )
    parsed = parse_records_jsonl(blob)
    assert [r.id for r in parsed] == ["a", "b"]


def test_turn_sidecar_path_is_zero_padded() -> None:
    assert turn_sidecar_path("S1", 0) == "sessions/S1/toolcalls/turn-0000.jsonl"
    assert turn_sidecar_path("S1", 42) == "sessions/S1/toolcalls/turn-0042.jsonl"
    assert turn_sidecar_path("S1", 12345) == "sessions/S1/toolcalls/turn-12345.jsonl"


# ---------------------------------------------------------------------------
# Fallback parser tests — VIS-2 (kaos-modules/docs/plans/...).
# ---------------------------------------------------------------------------


def test_parse_action_content_extracts_tool_name_and_summary() -> None:
    from app.services.tool_call_recorder import parse_action_content

    content = (
        "Tool: kaos-source-fr-search(()) → Found 38 Federal Register document(s), "
        'showing 20 (page 1 of 2) {"results": [{"document_number": "2025-18321"}]}'
    )
    rec = parse_action_content(content)
    assert rec is not None
    assert rec.name == "kaos-source-fr-search"
    assert rec.status == "done"
    assert "Found 38 Federal Register" in (rec.result_preview or "")
    # No args available from memory/actions — fallback is name + preview only.
    assert rec.args_preview is None


def test_parse_action_content_returns_none_for_non_tool() -> None:
    from app.services.tool_call_recorder import parse_action_content

    assert parse_action_content("") is None
    assert parse_action_content("not a tool line") is None
    assert parse_action_content("system: hello") is None


def test_parse_action_content_stable_id() -> None:
    from app.services.tool_call_recorder import parse_action_content

    content = "Tool: kaos-source-fr-search(()) → ok"
    r1 = parse_action_content(content)
    r2 = parse_action_content(content)
    assert r1 is not None and r2 is not None
    # Same input → same synthesized id, so React key stays stable across
    # re-fetches.
    assert r1.id == r2.id
    assert r1.id.startswith("kaos-source-fr-search-")


def test_parse_actions_into_records_skips_non_tool_items() -> None:
    from app.services.tool_call_recorder import parse_actions_into_records

    items = [
        {"content": "Tool: tool-a(()) → ok", "added_at": 1.0},
        {"content": "some non-tool log line", "added_at": 2.0},
        {"content": "Tool: tool-b(()) → done", "added_at": 3.0},
        {"content": "", "added_at": 4.0},
    ]
    recs = parse_actions_into_records(items)
    assert [r.name for r in recs] == ["tool-a", "tool-b"]


def test_records_dedup_orphan_running_with_same_name_done() -> None:
    # Regression for the "Agent Findings Dispatch running…" stuck-card bug:
    # kaos-agents <=0.1.22 emitted the findings-dispatch synthetic
    # tool_call's span_start with attrs.call_id = parent SUBAGENT span_id,
    # but span_complete omitted call_id so the recorder fell back to the
    # TOOL_CALL span's own span_id. Start and complete landed under
    # DIFFERENT keys, leaving an orphan "running" record alongside the
    # completed one. The dedup at .records() drops the orphan.
    rec = TurnToolCallRecorder()
    # Simulate the buggy emission: start with one call_id, complete with
    # another, both naming the same tool.
    rec.observe(
        "span",
        {
            "type": "span",
            "subject": "tool_call",
            "phase": "start",
            "span_id": "tc-span-A",
            "attributes": {
                "call_id": "parent-subagent-id",  # wrong — parent's id
                "tool_name": "kaos-agent-findings-dispatch",
            },
        },
    )
    rec.observe(
        "span",
        {
            "type": "span",
            "subject": "tool_call",
            "phase": "complete",
            "span_id": "tc-span-A",
            "attributes": {
                # NO call_id — recorder falls back to span_id "tc-span-A"
                "tool_name": "kaos-agent-findings-dispatch",
                "result_summary": "FindingsAgent: enumerated=11 filtered=1",
                "is_error": False,
            },
        },
    )
    records = rec.records()
    assert len(records) == 1, f"expected 1 record after dedup, got {[r.status for r in records]}"
    assert records[0].status == "done"
    assert records[0].result_preview == "FindingsAgent: enumerated=11 filtered=1"


def test_parse_records_jsonl_dedups_orphan_running_from_historical_sidecar() -> None:
    # Historical sidecars written before the source fix contain both the
    # orphan "running" record and the completed sibling. Loading them via
    # parse_records_jsonl applies the same dedup so old sessions render
    # as a single card.
    import json as _json

    lines = [
        _json.dumps(
            {
                "id": "parent-subagent-id",
                "name": "kaos-agent-findings-dispatch",
                "status": "running",
            }
        ),
        _json.dumps(
            {
                "id": "tc-span-A",
                "name": "kaos-agent-findings-dispatch",
                "status": "done",
                "result_preview": "FindingsAgent: enumerated=11 filtered=1",
            }
        ),
    ]
    blob = ("\n".join(lines)).encode("utf-8")
    records = parse_records_jsonl(blob)
    assert len(records) == 1
    assert records[0].status == "done"
    assert records[0].result_preview == "FindingsAgent: enumerated=11 filtered=1"
