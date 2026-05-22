"""Worker adapter — wraps :func:`stream_chat` for :func:`run_agentic_turn`.

The AgenticLoop orchestrator
(:func:`kaos_agents.patterns.agentic_loop.run_agentic_turn`) accepts an
injected ``WorkerCallable`` that runs one ReAct iteration. The
single-user-chat backend doesn't host the ReAct loop in-process — it
proxies to the bundled kaos-agents API over httpx (ASGITransport in
single-user-chat, real network in any future hosted variant). This
module adapts the existing :func:`stream_chat` SSE pump into the
``WorkerCallable`` shape the orchestrator expects.

**Closure pattern.** :func:`make_worker` is a factory that captures the
per-turn invariants (httpx client, bearer token, SessionMeta, budget,
catalog, corpus). The returned callable then varies only on the
per-iteration inputs the loop controls (``user_message``,
``allowed_groups``, ``thinking_note``, ``iteration``).

**Thinking-note threading.** Per the design plan §7.3 (option C —
*thinking block, not fake user message*), the loop's
``thinking_note`` (a single critic-emitted ``next_action`` line) is
threaded into the system instructions on iteration 2+, NOT injected
as a synthetic user turn. This avoids the kaos-agents memory storing
fake "user said X" entries and keeps the message ledger truthful.

**Event collection.** Every SSE record that :func:`stream_chat`
yields is captured into :attr:`WorkerResult.events` verbatim
(``{event, data}`` shape, where ``data`` is a JSON string). The
orchestrator forwards these through to the chat router's SSE stream
via the standard ``async for ev in worker_result.events: yield ev``
pattern (see :func:`kaos_agents.patterns.agentic_loop.run_agentic_turn`).

**Cost + tool-call accounting.** Sourced from the upstream wire:

  - Tool calls — every ``tool_call_summary`` event (one per completed
    call) is appended to :attr:`WorkerResult.tool_calls_made`.
  - Text — every ``text_delta`` event's ``content`` is concatenated
    into :attr:`WorkerResult.text`.
  - Cost — the final ``turn_summary`` carries the aggregate
    ``cost_usd``; we read that. Falls back to summing
    ``usage_observed`` events if no ``turn_summary`` shows up
    (defensive — happens on hard early termination).
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx
from kaos_agents.patterns.agentic_loop import WorkerCallable, WorkerResult

from app.models import SessionMeta, SessionToolSetWire
from app.services.stream_proxy import stream_chat


def make_worker(
    *,
    client: httpx.AsyncClient,
    bearer_token: str,
    meta: SessionMeta,
    max_cost_usd: float,
    available_tool_names: Sequence[str] | None = None,
    corpus_markdown: str = "",
) -> WorkerCallable:
    """Construct a :class:`WorkerCallable` for :func:`run_agentic_turn`.

    Captures the per-turn invariants in a closure; the returned
    callable accepts only the per-iteration inputs the loop varies.

    Args:
        client: ``httpx.AsyncClient`` wired to the bundled kaos-agents
            ASGI app (or a real network host).
        bearer_token: Auth token forwarded to ``stream_chat``. Empty
            string falls back to env-var inside ``stream_chat``.
        meta: The :class:`SessionMeta` for this session — supplies
            ``model``, ``system_prompt``, ``policy.denied_tools``, etc.
        max_cost_usd: Per-turn budget. Each iteration shares this cap;
            the AgenticLoop applies its own cumulative cap on top.
        available_tool_names: Optional pre-fetched list of every tool
            in the runtime catalog. When provided, the proxy filters
            against it for precision; when omitted, falls back to
            group-prefix globs.
        corpus_markdown: Optional rendered corpus block, inlined into
            the system prompt by ``_instructions_with_corpus``.

    Returns:
        A callable matching the
        :class:`~kaos_agents.patterns.agentic_loop.WorkerCallable`
        signature: ``(user_message, allowed_groups, thinking_note,
        iteration) -> WorkerResult``.
    """

    async def _worker(
        *,
        user_message: str,
        allowed_groups: list[str],
        thinking_note: str,
        iteration: int,
        **_unused: Any,  # forward-compat with future loop kwargs
    ) -> WorkerResult:
        # ── 1. Per-iteration tool_set override ───────────────────────
        # The loop hands us the planner-narrowed set for this iteration.
        # Wrap it as a SessionToolSetWire so stream_chat's existing
        # tool_set_override path applies (no new code in stream_chat).
        per_iter_tool_set = SessionToolSetWire(
            allowed_groups=list(allowed_groups),
            denied_tools=list(meta.policy.denied_tools),
            # The AgenticLoop already narrowed; don't let the legacy
            # turn_tool_policy planner run again inside the proxy.
            auto_narrow=False,
        )

        # ── 2. Thinking-note on replan iterations ────────────────────
        # Design plan §7.3 / option C — append to system instructions
        # instead of inventing a user turn. Empty note (iteration 1)
        # leaves meta untouched so the prompt cache stays warm.
        if iteration > 1 and thinking_note:
            augmented_meta = meta.model_copy(
                update={
                    "system_prompt": (
                        f"{meta.system_prompt}\n\n"
                        "## Replan guidance from the critic\n\n"
                        f"{thinking_note}\n\n"
                        "Use this guidance to inform your next action."
                    )
                }
            )
        else:
            augmented_meta = meta

        # ── 3. Pump the upstream stream + collect ────────────────────
        # Iteration-leak fix (task #458, plan
        # docs/plans/2026-05-19-agentic-loop-honesty.md §3.1.a):
        # **every** critic-driven iteration (including iteration 1)
        # sets ``is_internal_iteration=True`` on the upstream POST so
        # the kaos-agents BaseAgent skips writing user + intermediate
        # assistant messages to SessionMemory.MESSAGES. After the loop
        # terminates, the SPA's ``send_message`` finally-block POSTs
        # the canonical (user_message, final_worker_text) pair to
        # ``/v1/sessions/{id}/memory/messages/turn`` via
        # :func:`persist_canonical_turn` — the post-loop write is the
        # SINGLE source of truth for persisted messages, so memory has
        # exactly one user entry + one assistant entry per user turn
        # no matter how many iterations the loop ran. Previously the
        # iter-1 path passed False and the post-loop write added a
        # second pair (4 entries persisted for a 3-iter turn); fixed
        # 2026-05-20 (task #498).
        is_internal = True
        t_start = time.monotonic()
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        # Cost: prefer turn_summary's aggregate; fall back to summing
        # usage_observed for hard-early-termination paths.
        turn_summary_cost_usd: float | None = None
        usage_sum_cost_usd: float = 0.0
        captured_events: list[dict[str, str]] = []

        async for record in stream_chat(
            client=client,
            bearer_token=bearer_token,
            meta=augmented_meta,
            message=user_message,
            max_cost_usd=max_cost_usd,
            available_tool_names=available_tool_names,
            corpus_markdown=corpus_markdown,
            tool_set_override=per_iter_tool_set,
            is_internal_iteration=is_internal,
        ):
            captured_events.append(record)
            payload = _parse_payload(record)
            if payload is None:
                continue
            event_type = payload.get("type", "")
            if event_type == "text_delta":
                content = payload.get("content")
                if isinstance(content, str):
                    text_parts.append(content)
            elif event_type == "span" and payload.get("subject") == "tool_call":
                # ROOT CAUSE OF #548 (WU-K v2 matrix, 5-of-5
                # reproductions on tool-dispatch turns).
                #
                # Before this fix the worker listened for
                # `event_type == "tool_call_summary"` — but the
                # kaos-agents wire stream does NOT emit a standalone
                # `tool_call_summary` event. `ToolCallSummary` only
                # exists as a nested field inside
                # `TurnSummary.tool_calls` (see
                # `kaos_agents/events/tools.py` +
                # `kaos_agents/events/lifecycle.py`). The old branch
                # was dead code, so `tool_calls` was ALWAYS `[]`
                # regardless of how many tools the worker actually
                # ran. The GoalCheckerSignature
                # (`kaos_agents/planning/goal_check.py:483-489`)
                # then received an empty list every turn, and its
                # rules at lines 425-445 ("Factual-external-entity
                # question with zero successful tool calls") fired
                # correctly given what they saw — but mismatched
                # against reality. The persisted refusal text
                # "tool_calls_made is empty" was literally true at
                # the data-flow level, even though the actual trace
                # had 5+ status=done tool spans.
                #
                # Fix: read tool calls from the canonical `span`
                # events with `subject="tool_call", phase="complete"`
                # — the same source the SPA's
                # `tool_call_recorder.py` uses to build the persisted
                # UI tool-card list. Build the exact dict shape the
                # GoalCheckerSignature documents:
                # `{name, is_error, summary_excerpt}`.
                if payload.get("phase") != "complete":
                    continue
                attrs = payload.get("attributes") or {}
                if not isinstance(attrs, dict):
                    continue
                tool_name = str(attrs.get("tool_name") or "")
                if not tool_name:
                    continue
                is_error = bool(attrs.get("is_error", False))
                result_summary = attrs.get("result_summary") or attrs.get("result") or ""
                if not isinstance(result_summary, str):
                    result_summary = str(result_summary)
                tool_calls.append(
                    {
                        # ── kaos-agents GoalChecker contract ────────
                        "name": tool_name,
                        "is_error": is_error,
                        "summary_excerpt": result_summary[:800],
                        # ── enrichment for downstream consumers ─────
                        "tool_name": tool_name,
                        "call_id": attrs.get("call_id"),
                        "result_summary": result_summary,
                        "structured_content": attrs.get("structured_content"),
                    }
                )
            elif event_type == "turn_summary":
                cost = payload.get("cost_usd")
                if isinstance(cost, int | float):
                    turn_summary_cost_usd = float(cost)
            elif event_type == "usage_observed":
                cost = payload.get("cost_usd")
                if isinstance(cost, int | float):
                    usage_sum_cost_usd += float(cost)
                    # Plan Issue 9 SPA layer — emit a synthetic
                    # ``cost_forecast`` SSE event so the UI's RunInspector
                    # can render a running-total cost line + warn at 80%
                    # of cap mid-stream. The kaos-agents wire surfaces
                    # per-LLM-call ``usage_observed`` but never a rolling
                    # turn-total; the UI today has to wait for
                    # ``turn_summary`` (end of run) to see the number.
                    # By injecting a synthetic event into
                    # ``captured_events`` we keep the wire shape additive
                    # (no breaking change for consumers that ignore
                    # unknown event types) while giving the UI an
                    # actionable mid-iteration signal.
                    forecast_event = {
                        "event": "cost_forecast",
                        "data": json.dumps(
                            {
                                "type": "cost_forecast",
                                "cost_usd_so_far": round(
                                    usage_sum_cost_usd, 6
                                ),
                                "max_cost_usd": max_cost_usd,
                                "fraction_used": (
                                    round(usage_sum_cost_usd / max_cost_usd, 4)
                                    if max_cost_usd > 0
                                    else None
                                ),
                                "warn_threshold_reached": (
                                    usage_sum_cost_usd >= 0.8 * max_cost_usd
                                    if max_cost_usd > 0
                                    else False
                                ),
                            }
                        ),
                    }
                    captured_events.append(forecast_event)

        latency_ms = (time.monotonic() - t_start) * 1000.0
        cost_usd = (
            turn_summary_cost_usd if turn_summary_cost_usd is not None else usage_sum_cost_usd
        )

        return WorkerResult(
            text="".join(text_parts),
            tool_calls_made=tool_calls,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            events=list(captured_events),
        )

    return _worker


async def persist_canonical_turn(
    *,
    client: httpx.AsyncClient,
    bearer_token: str,
    session_id: str,
    user_message: str,
    assistant_message: str,
) -> bool:
    """POST the canonical (user, final-assistant) pair to the new
    ``/v1/sessions/{id}/memory/messages/turn`` endpoint.

    Called by the SPA's ``send_message`` handler exactly once at the
    end of an AgenticLoop turn — companion to the
    ``is_internal_iteration=True`` flag the worker sets on every
    upstream POST (see task #458 / plan
    docs/plans/2026-05-19-agentic-loop-honesty.md §3.1.a).

    Returns True on a 2xx response, False otherwise. Failures are
    logged but never re-raised — losing the canonical write degrades
    the next turn's context assembly but must not break the turn the
    user just observed succeed.
    """
    body = {
        "user_message": user_message,
        "assistant_message": assistant_message,
    }
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = await client.post(
            f"/v1/sessions/{session_id}/memory/messages/turn",
            headers=headers,
            json=body,
        )
    except httpx.HTTPError:
        return False
    return 200 <= resp.status_code < 300


def _parse_payload(record: dict[str, str]) -> dict[str, Any] | None:
    """Decode ``record['data']`` as JSON, returning None on any failure.

    SSE records carry ``data`` as a JSON-encoded string. We never want
    a malformed event to take down the whole turn — return None so the
    caller can skip it.
    """
    raw = record.get("data")
    if not isinstance(raw, str):
        return None
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None
