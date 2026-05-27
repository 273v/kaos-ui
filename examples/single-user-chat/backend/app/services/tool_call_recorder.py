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

### Scope — wire-level only (#447 documented limitation)

The sidecar captures the **wire-level subset** of tool calls — the ones
that fire ``Span(TOOL_CALL, ...)`` SSE events because they emit chips
into the UI. It does NOT capture:

- Planner Signature LLM calls
- Critic / GoalCheck / M2-Consistency Signature LLM calls
- IntentSignature classification calls
- Auto-titler LLM calls
- Other internal agent reasoning calls that don't surface as
  user-visible tool activity

Those internal calls land in ``SessionMemory.ACTIONS`` (kaos-agents'
own action trace) but never as ``Span(TOOL_CALL, ...)`` because they
aren't tools — they're internal reasoning steps. This means:

- For **live chip UI rendering**: the sidecar is correct + sufficient.
  Chips show user-visible tool activity, which is what users want.
- For **full agent activity audit**: ALWAYS read kaos-agents' own
  ``/v1/sessions/{id}/memory/actions`` endpoint. That's the canonical
  source. The ``kaos-audit-session`` CLI (#441) routes here.

Persona-matrix audits that compared sidecar.jsonl vs memory.json on
2026-05-19 flagged this as "recorder undercount" (#447) — that was
correct as a finding but the SPA recorder behavior is by-design.
The audit CLI is the right consumer for the full trace; the sidecar
is the right consumer for the chip UI. Two surfaces, two consumers.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from app.logging_setup import app_logger

logger = app_logger("tool_call_recorder")


ToolCallStatus = Literal["running", "done", "error"]


class ToolCallRecord(BaseModel):
    """Persisted shape of one tool call within a turn.

    Mirrors the SPA's `ToolCallSummary` shape so the history-hydration
    path can pass the record through with minimal transformation.
    """

    id: str
    name: str
    status: ToolCallStatus
    args_preview: str | None = None
    result_preview: str | None = None
    structured_content: dict[str, Any] | None = None
    """Full tool ``ToolResult.structuredContent`` dict (Stage C of the
    no-hardcoded-caps-and-artifact-first-tool-results plan). Carries
    ``artifact_id`` / ``body_uri`` / ``source_uri`` / ``size`` /
    ``mime_type`` for artifact-emitting tools so the SPA's ArtifactCard
    can render the file inline. ``None`` for tools that don't ship
    structured output."""

    # #342 enrichment fields. All optional so legacy sidecars without
    # them still parse cleanly.
    duration_ms: float | None = None
    """Wall-clock time the tool call took. From ``Span(TOOL_CALL,
    COMPLETE).duration_ms`` if the wire payload carries it, else
    derived from start/end timestamps. ``None`` when the recorder
    saw only the complete phase (start was already lost)."""

    cost_usd: float | None = None
    """LLM cost attributable to this tool call when the tool itself
    drove an LLM call (RAG's rag-query verifier, delegated sub-agent).
    From ``ToolCallSummary.cost_usd``. ``0.0`` for plain tools that
    don't call an LLM; ``None`` when the wire didn't surface the
    field at all (older kaos-agents versions)."""

    plan_id: str | None = None
    """Plan ID when the call ran inside a plan-execute pattern; ``None``
    for chat / research / direct-respond turns."""

    step_id: str | None = None
    """Plan step ID when the call ran inside a plan-execute pattern;
    correlated with ``plan_id``."""


class TurnUsageRecorder:
    """Stateful tap for ``usage_observed`` + ``turn_summary`` SSE events.

    The kaos-agents wire stream emits one ``usage_observed`` event per
    LLM call (planner Signature, critic Signature, worker text-gen,
    auto-titler) plus a ``turn_summary`` at the very end carrying the
    final aggregate. Both shapes have ``cost_usd`` and ``total_tokens``
    fields. We prefer the ``turn_summary`` aggregate when present
    because it includes Signature-level calls the SPA otherwise can't
    see (per UX-A4 #342). Fall back to summing the per-call
    ``usage_observed`` events for partial-completion paths.

    Companion to :class:`TurnToolCallRecorder` — the chat router pipes
    every SSE event into ``observe()`` for both recorders.
    """

    def __init__(self) -> None:
        # Sum of every per-call ``usage_observed`` event seen this turn.
        # Includes worker LLM calls + critic calls + planner calls —
        # every Signature invocation that emits a UsageObserved event.
        self._usage_sum_cost_usd: float = 0.0
        self._usage_sum_input_tokens: int = 0
        self._usage_sum_output_tokens: int = 0
        # The final ``turn_summary`` aggregate, if it arrived. Tuple
        # of (cost_usd, total_tokens). None until the event fires.
        # R2.3 #567: this is the WORKER iteration's aggregate (one per
        # ReAct dispatch), NOT the whole turn — replaces on each
        # iteration. Kept only as a non-fatal cross-check.
        self._final_summary: tuple[float, int] | None = None
        # R2.3 #567: ``loop_terminated`` carries the orchestrator's
        # authoritative aggregate across worker + planner + every critic
        # call. Prefer this when it arrives — it's the same number
        # ``state.cumulative_cost_usd`` reports in kaos-agents itself
        # (see ``LoopTerminated.cost_usd`` docstring at
        # ``kaos_agents/events/policy.py:219-227``).
        self._loop_terminated_summary: tuple[float, int] | None = None

    def observe(self, event_name: str, payload: Any) -> None:
        """Inspect one SSE event and update the running totals.

        Recognized event shapes (per kaos_agents wire serializers):
        - ``turn_summary`` event: payload carries ``cost_usd`` (float)
          and ``total_tokens`` (int). Per WORKER iteration aggregate.
        - ``usage_observed`` event: payload carries ``cost_usd``,
          ``input_tokens``, ``output_tokens``. Per LLM call —
          including critics + planner.
        - ``loop_terminated`` event (R2.3 #567): the orchestrator's
          authoritative aggregate across every LLM call in the turn.
          Wire shape carries ``cost_usd``; total_tokens is summed
          from observed usage_observed events because LoopTerminated
          doesn't carry token counts directly (only cost).
        """
        if not isinstance(payload, dict):
            return
        if event_name == "turn_summary":
            cost = payload.get("cost_usd")
            total_tokens = payload.get("total_tokens")
            if isinstance(cost, int | float) and isinstance(total_tokens, int):
                self._final_summary = (float(cost), int(total_tokens))
            return
        if event_name == "loop_terminated":
            # R2.3 #567: authoritative whole-turn cost aggregate.
            cost = payload.get("cost_usd")
            if isinstance(cost, int | float):
                # LoopTerminated doesn't ship token counts; pair with
                # the running usage sum so the (cost, tokens) tuple
                # stays usable downstream.
                tokens = self._usage_sum_input_tokens + self._usage_sum_output_tokens
                self._loop_terminated_summary = (float(cost), tokens)
            return
        if event_name == "usage_observed":
            cost = payload.get("cost_usd")
            in_tok = payload.get("input_tokens")
            out_tok = payload.get("output_tokens")
            if isinstance(cost, int | float):
                self._usage_sum_cost_usd += float(cost)
            if isinstance(in_tok, int):
                self._usage_sum_input_tokens += in_tok
            if isinstance(out_tok, int):
                self._usage_sum_output_tokens += out_tok

    def snapshot(self) -> tuple[float, int]:
        """Return ``(cost_usd, total_tokens)`` for the completed turn.

        Preference order (most authoritative first):

        1. R2.3 #567: ``loop_terminated.cost_usd`` — the orchestrator's
           aggregate across worker + planner + every critic. Matches
           ``state.cumulative_cost_usd`` in kaos-agents. Required for
           critic-heavy turns where the worker's ``turn_summary`` only
           covers the ReAct dispatch and misses M2/M3/GoalCheck spend
           (Agent 5's diary: meta reported $0.0014 vs true $0.0091, a
           5-6x under-count pre-R2.3).
        2. Sum of ``usage_observed`` events — covers every LLM call we
           saw, including critic + planner calls between worker
           iterations. Fires when ``loop_terminated`` doesn't arrive
           (network drop, hard early exit).
        3. The last ``turn_summary`` aggregate alone — least authoritative
           because it's per-WORKER-ITERATION (clobbered on each iter)
           and excludes critic costs entirely. Retained as a last-resort
           fallback for streams that never emit either of the above.
        """
        if self._loop_terminated_summary is not None:
            return self._loop_terminated_summary
        if self._usage_sum_cost_usd > 0:
            return (
                self._usage_sum_cost_usd,
                self._usage_sum_input_tokens + self._usage_sum_output_tokens,
            )
        if self._final_summary is not None:
            return self._final_summary
        return (
            self._usage_sum_cost_usd,
            self._usage_sum_input_tokens + self._usage_sum_output_tokens,
        )


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
            raw_structured = attrs.get("structured_content")
            structured_content = raw_structured if isinstance(raw_structured, dict) else None
            # #342 enrichment: pull cost, timing, plan linkage from the
            # span's attributes + payload. All are optional — older
            # kaos-agents versions don't emit them, and chat/research
            # turns won't have plan_id/step_id even on current versions.
            duration_ms = payload.get("duration_ms")
            if not isinstance(duration_ms, int | float):
                duration_ms = None
            cost_usd = attrs.get("cost_usd")
            if not isinstance(cost_usd, int | float):
                cost_usd = None
            plan_id = attrs.get("plan_id")
            if not isinstance(plan_id, str):
                plan_id = None
            step_id = attrs.get("step_id")
            if not isinstance(step_id, str):
                step_id = None
            updates: dict[str, Any] = {
                "name": tool_name,
                "status": status,
            }
            if result_preview is not None:
                updates["result_preview"] = result_preview
            if structured_content is not None:
                updates["structured_content"] = structured_content
            if duration_ms is not None:
                updates["duration_ms"] = float(duration_ms)
            if cost_usd is not None:
                updates["cost_usd"] = float(cost_usd)
            if plan_id is not None:
                updates["plan_id"] = plan_id
            if step_id is not None:
                updates["step_id"] = step_id
            self._by_id[call_id] = (
                existing.model_copy(update=updates)
                if existing is not None
                else ToolCallRecord(
                    id=call_id,
                    name=tool_name,
                    status=status,
                    result_preview=result_preview,
                    structured_content=structured_content,
                    duration_ms=float(duration_ms) if duration_ms is not None else None,
                    cost_usd=float(cost_usd) if cost_usd is not None else None,
                    plan_id=plan_id,
                    step_id=step_id,
                )
            )
        elif phase == "error":
            err_msg = payload.get("error_message") or "tool error"
            updates = {"name": tool_name, "status": "error", "result_preview": err_msg}
            self._by_id[call_id] = (
                existing.model_copy(update=updates)
                if existing is not None
                else ToolCallRecord(id=call_id, **updates)  # ty: ignore[invalid-argument-type]
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


# ---------------------------------------------------------------------------
# Fallback parser — used when the sidecar is missing or empty for a turn.
#
# kaos-agents serializes SessionMemory.ACTIONS items as flattened content
# strings via /v1/sessions/{id}/memory/actions: the rich tool_execution
# metadata on disk (tool_name, args, result_summary, duration_ms, is_error,
# cost_usd) is collapsed into a single one-line summary that looks like:
#
#   Tool: kaos-source-fr-search(()) → Found 38 Federal Register documents...
#
# (followed by an optional JSON-blob body separated by `\n\n`).
#
# The sidecar writer (TurnToolCallRecorder) is the preferred source — it
# captures structured fields off the live SSE stream. But if the stream
# dies before any tool_call_summary event flushes (client disconnects,
# StreamingResponse cancels, recorder.observe never runs), the sidecar
# is empty and chips disappear from the reloaded transcript even though
# the agent persisted real tool calls.
#
# As a backstop, the /messages handler re-reads memory/actions and parses
# the content strings into ToolCallRecord rows. The reconstructed records
# carry tool_name + result_preview but not args_preview (the API drops
# args). That's "enough so the user knows tools ran" — the long-term fix
# is for kaos-agents to expose the structured tool_execution metadata
# via the memory API (filed for a future release).
# ---------------------------------------------------------------------------


_TOOL_CONTENT_RE = re.compile(
    r"^Tool:\s*(?P<name>[\w.\-:]+)\s*\(.*?\)\s*→\s*(?P<summary>.+)", re.DOTALL
)


def parse_action_content(content: str) -> ToolCallRecord | None:
    """Parse one memory/actions content string back into a ToolCallRecord.

    The kaos-agents API renders ACTIONS items as
    ``Tool: <name>(<args>) → <summary>[\\n\\n<body>]`` — see the comment
    above for context. Returns ``None`` when the content doesn't match
    (e.g., a non-tool action, an empty string, or a future format).
    """
    if not isinstance(content, str) or not content:
        return None
    m = _TOOL_CONTENT_RE.match(content.strip())
    if m is None:
        return None
    name = m.group("name").strip()
    summary = m.group("summary").strip()
    # The summary line is followed by an optional `\n\n{json}` blob. Keep
    # the full thing as result_preview so the expander shows the agent's
    # actual return; truncate so chip-render doesn't pull megabytes.
    preview = summary[:2000]
    # We don't get a stable call_id from the API. Synthesize one from the
    # tool name + a short hash of the content so the React key stays
    # stable across re-fetches.
    import hashlib

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    return ToolCallRecord(
        id=f"{name}-{digest}",
        name=name,
        status="done",
        result_preview=preview,
    )


def parse_actions_into_records(items: list[dict[str, Any]]) -> list[ToolCallRecord]:
    """Map a list of memory/actions items into ToolCallRecord rows.

    Items that don't look like tool actions are silently skipped. Order
    is preserved (kaos-agents newest-first → caller may want to reverse).
    """
    records: list[ToolCallRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = parse_action_content(item.get("content", ""))
        if record is not None:
            records.append(record)
    return records


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
