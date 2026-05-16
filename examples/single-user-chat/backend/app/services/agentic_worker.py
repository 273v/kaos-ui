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
            elif event_type == "tool_call_summary":
                tool_calls.append(payload)
            elif event_type == "turn_summary":
                cost = payload.get("cost_usd")
                if isinstance(cost, int | float):
                    turn_summary_cost_usd = float(cost)
            elif event_type == "usage_observed":
                cost = payload.get("cost_usd")
                if isinstance(cost, int | float):
                    usage_sum_cost_usd += float(cost)

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
