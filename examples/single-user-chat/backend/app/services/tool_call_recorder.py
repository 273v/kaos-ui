"""Capture tool-call activity off the SSE stream into a VFS sidecar.

kaos-agents 0.1.0a1 does not persist per-turn tool-call records in a
shape the SPA can hydrate later — `SessionMemory.ACTIONS` stores a
lossy string summary, and there's no `assistant_message_id` linking
calls to the message they served. The wire-side SSE events DO carry
the structured tool name + args + result_summary (truncated to 200
chars), so we tee them as the stream flows by and persist one JSONL
file per turn.

Layout:

    sessions/{session_id}/toolcalls/
        turn-0000.jsonl     # first user→assistant turn
        turn-0001.jsonl     # second turn
        ...

Each line is a `ToolCallRecord.model_dump_json()` blob. Newest-line-
wins on duplicate `call_id` so re-runs are idempotent.

The recorder is intentionally pure — it doesn't reach into kaos-agents
internals or the VFS. The caller hands it events one by one and then
asks it to flush to a path.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.logging_setup import app_logger

logger = app_logger("tool_call_recorder")


class ToolCallRecord(BaseModel):
    """Persisted shape of one tool call within a turn.

    Mirrors the SPA's `ToolCallSummary` shape so the history-hydration
    path can pass the record through with minimal transformation.
    """

    id: str
    name: str
    status: str
    args_preview: str | None = None
    result_preview: str | None = None


class TurnToolCallRecorder:
    """Stateful tap that consumes SSE events and emits ToolCallRecord rows.

    Call ``observe(event_name, payload)`` for each event as it streams
    past. When the stream ends, call ``records()`` to retrieve the
    list ordered by first-seen time. The caller is responsible for
    writing the result to the VFS — keeping persistence out of the
    recorder lets it stay synchronous + easy to unit test.
    """

    def __init__(self) -> None:
        # call_id → record. Dict insertion order preserves first-seen
        # arrival, which matches the order the assistant invoked tools.
        self._by_id: dict[str, ToolCallRecord] = {}

    def observe(self, event_name: str, payload: Any) -> None:
        """Inspect one SSE event payload and update the in-flight map.

        Recognized event shapes (per kaos_agents.patterns.chat):
        - span/tool_call/start: attributes.{tool_name, call_id}
        - span/tool_call/complete: attributes.{tool_name, call_id,
              result_summary, is_error}
        - tool_call_args_delta: tool_name + call_id + delta chunks
        """
        if event_name != "span":
            if event_name == "tool_call_args_delta":
                self._observe_args_delta(payload)
            return
        if not isinstance(payload, dict):
            return
        if payload.get("subject") != "tool_call":
            return
        phase = payload.get("phase")
        attrs = payload.get("attributes") or {}
        call_id = attrs.get("call_id") or payload.get("span_id")
        tool_name = attrs.get("tool_name") or "tool"
        if not isinstance(call_id, str) or not call_id:
            return
        existing = self._by_id.get(call_id)
        if phase == "start":
            if existing is None:
                self._by_id[call_id] = ToolCallRecord(id=call_id, name=tool_name, status="running")
            else:
                self._by_id[call_id] = existing.model_copy(
                    update={"name": tool_name, "status": "running"}
                )
        elif phase == "complete":
            status = "error" if attrs.get("is_error") else "done"
            result_preview = attrs.get("result_summary") or attrs.get("result")
            if not isinstance(result_preview, str):
                result_preview = None
            updates: dict[str, Any] = {
                "name": tool_name,
                "status": status,
            }
            if result_preview is not None:
                updates["result_preview"] = result_preview
            self._by_id[call_id] = (
                existing.model_copy(update=updates)
                if existing is not None
                else ToolCallRecord(
                    id=call_id, name=tool_name, status=status, result_preview=result_preview
                )
            )
        elif phase == "error":
            err_msg = payload.get("error_message") or "tool error"
            updates = {"name": tool_name, "status": "error", "result_preview": err_msg}
            self._by_id[call_id] = (
                existing.model_copy(update=updates)
                if existing is not None
                else ToolCallRecord(id=call_id, **updates)  # type: ignore[arg-type]
            )

    def _observe_args_delta(self, payload: Any) -> None:
        """Accumulate streamed `tool_call_args_delta` chunks into args_preview."""
        if not isinstance(payload, dict):
            return
        call_id = payload.get("call_id") or payload.get("tool_name")
        delta = payload.get("delta")
        if not isinstance(call_id, str) or not isinstance(delta, str):
            return
        existing = self._by_id.get(call_id)
        tool_name = payload.get("tool_name") or (existing.name if existing else "tool")
        current_args = (existing.args_preview if existing else "") or ""
        next_args = (current_args + delta)[:512]  # bound to avoid runaway memory
        if existing is None:
            self._by_id[call_id] = ToolCallRecord(
                id=call_id,
                name=tool_name if isinstance(tool_name, str) else "tool",
                status="running",
                args_preview=next_args,
            )
        else:
            self._by_id[call_id] = existing.model_copy(
                update={
                    "name": tool_name if isinstance(tool_name, str) else existing.name,
                    "args_preview": next_args,
                }
            )

    def records(self) -> list[ToolCallRecord]:
        """Return the accumulated tool-call rows in first-seen order."""
        return list(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id


def turn_sidecar_path(session_id: str, turn_index: int) -> str:
    """VFS path for the per-turn tool-call sidecar."""
    return f"sessions/{session_id}/toolcalls/turn-{turn_index:04d}.jsonl"


def serialize_records(records: list[ToolCallRecord]) -> bytes:
    """JSONL serialization — one record per line, UTF-8 encoded."""
    return b"\n".join(r.model_dump_json().encode("utf-8") for r in records) + b"\n"


def parse_records_jsonl(blob: bytes | str) -> list[ToolCallRecord]:
    """Inverse of `serialize_records`. Skips malformed lines defensively."""
    text = blob.decode("utf-8", errors="replace") if isinstance(blob, bytes) else blob
    out: list[ToolCallRecord] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            out.append(ToolCallRecord.model_validate(obj))
        except Exception as exc:
            logger.warning("dropping malformed toolcall record %r: %s", line[:80], exc)
            continue
    return out
