"""Tests for ``app.services.agentic_worker.make_worker``.

The worker adapter wraps :func:`stream_chat` for the AgenticLoop's
``WorkerCallable`` contract. These tests stub out :func:`stream_chat`
so we exercise the adapter pure (no httpx, no asgi).

Coverage:
  - tool_set_override carries per-iteration allowed_groups
  - tool_set_override carries the session's denied_tools floor
  - tool_set_override forces ``auto_narrow=False`` (the loop already
    narrowed; the proxy must not run the legacy planner again)
  - iteration 1 leaves the system prompt untouched
  - iteration >= 2 with thinking_note appends a critic-guidance block
    to the system prompt
  - text concatenation from ``text_delta.content``
  - tool_calls_made collection from ``tool_call_summary``
  - cost_usd from ``turn_summary``
  - cost_usd fallback to summed ``usage_observed`` when no turn_summary
  - events list preserves the SSE record shape verbatim
  - malformed records (non-JSON data, unknown event types) are tolerated
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from kaos_agents.patterns.agentic_loop import WorkerResult

from app.models import SessionMeta, SessionPolicyWire
from app.services import agentic_worker, stream_proxy


async def _run_worker(worker: Any, **kwargs: Any) -> tuple[list[Any], WorkerResult]:
    """Drive a streaming worker (async generator) to completion.

    The worker yields its pass-through SSE records live, then a terminal
    :class:`WorkerResult`. Returns ``(streamed_events, final_result)``.
    """
    events: list[Any] = []
    result: WorkerResult | None = None
    async for item in worker(**kwargs):
        if isinstance(item, WorkerResult):
            result = item
        else:
            events.append(item)
    assert result is not None, "streaming worker did not yield a terminal WorkerResult"
    return events, result


class _StreamChatStub:
    """Replacement for ``stream_chat`` that records kwargs + replays records."""

    def __init__(self, records: list[dict[str, str]]) -> None:
        self._records = records
        self.captured: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> AsyncIterator[dict[str, str]]:
        self.captured.update(kwargs)
        return self._iter()

    async def _iter(self) -> AsyncIterator[dict[str, str]]:
        for r in self._records:
            yield r


def _client() -> httpx.AsyncClient:
    """A bare AsyncClient — the stub never actually calls it."""
    return httpx.AsyncClient()


def _meta(*, system_prompt: str = "Be helpful.") -> SessionMeta:
    return SessionMeta(
        id="01J1234567890123456789ABCD",
        title="t",
        model="anthropic:claude-haiku-4-5",
        system_prompt=system_prompt,
        policy=SessionPolicyWire.for_persona("research"),
        created_at=datetime(2026, 5, 14, tzinfo=UTC),
        last_message_at=None,
        message_count=0,
        archived=False,
    )


def _sse(event_type: str, **payload: Any) -> dict[str, str]:
    """Build one SSE record in the wire shape stream_chat emits."""
    body = {"type": event_type, **payload}
    return {"event": event_type, "data": json.dumps(body)}


def _tool_call_span(
    *,
    tool_name: str,
    call_id: str,
    is_error: bool = False,
    result_summary: str = "",
    structured_content: dict[str, Any] | None = None,
    phase: str = "complete",
) -> dict[str, str]:
    """Build a `span` SSE record for a TOOL_CALL phase.

    Mirrors the wire shape kaos-agents emits from
    ``kaos_agents.patterns.chat`` — see chat.py:630-654 for the
    upstream emitter. The SPA worker reads tool calls from these
    span/complete events (post-#548 fix); see
    ``app/services/agentic_worker.py:180``.
    """
    attrs: dict[str, Any] = {
        "tool_name": tool_name,
        "call_id": call_id,
        "is_error": is_error,
        "result_summary": result_summary,
    }
    if structured_content is not None:
        attrs["structured_content"] = structured_content
    body = {
        "type": "span",
        "subject": "tool_call",
        "phase": phase,
        "attributes": attrs,
    }
    return {"event": "span", "data": json.dumps(body)}


def _stream_chat_stub(records: list[dict[str, str]]) -> _StreamChatStub:
    """Return a callable stub for stream_chat that captures kwargs + replays records."""
    return _StreamChatStub(records)


async def test_iter1_uses_meta_system_prompt_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.001)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta(system_prompt="Be terse.")
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents", "vfs"],
        thinking_note="",
        iteration=1,
    )

    forwarded_meta: SessionMeta = fake.captured["meta"]
    assert forwarded_meta.system_prompt == "Be terse."


async def test_iter2_appends_thinking_note_to_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.001)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta(system_prompt="Base prompt.")
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents"],
        thinking_note="Try searching the corpus first.",
        iteration=2,
    )

    forwarded_meta: SessionMeta = fake.captured["meta"]
    assert forwarded_meta.system_prompt.startswith("Base prompt.")
    assert "Replan guidance" in forwarded_meta.system_prompt
    assert "Try searching the corpus first." in forwarded_meta.system_prompt


async def test_iter2_with_empty_thinking_note_does_not_augment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty thinking_note means the critic produced no guidance — don't add a banner."""
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.0)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta(system_prompt="Untouched.")
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=2,
    )

    forwarded_meta: SessionMeta = fake.captured["meta"]
    assert forwarded_meta.system_prompt == "Untouched."


async def test_tool_set_override_carries_per_iter_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.0)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents", "citations"],
        thinking_note="",
        iteration=1,
    )

    override = fake.captured["tool_set_override"]
    assert sorted(override.allowed_groups) == ["citations", "documents"]


async def test_tool_set_override_pins_denied_tools_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.0)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents"],
        thinking_note="",
        iteration=1,
    )

    override = fake.captured["tool_set_override"]
    # Default research persona deny-list bakes in the 4 self-recursive
    # kaos-agents tools — they must survive into the per-iteration set.
    assert "kaos-agent-chat" in override.denied_tools
    assert "kaos-agent-plan" in override.denied_tools


async def test_tool_set_override_disables_auto_narrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AgenticLoop already narrowed for this iteration — the
    legacy turn_tool_policy planner in stream_proxy must NOT re-run.
    """
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.0)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents"],
        thinking_note="",
        iteration=1,
    )

    override = fake.captured["tool_set_override"]
    assert override.auto_narrow is False


async def test_text_concatenation_from_text_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _sse("text_delta", content="Hello "),
        _sse("text_delta", content="world"),
        _sse("text_delta", content="!"),
        _sse("turn_summary", cost_usd=0.002),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=1,
    )

    assert result.text == "Hello world!"


async def test_tool_calls_collected_from_span_complete_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool calls are read from `span` events with subject=tool_call, phase=complete.

    Pre-#548 the worker listened for a `tool_call_summary` SSE event
    that kaos-agents never emits as a standalone wire event (see
    kaos_agents.events.tools.ToolCallSummary — it only ships inside
    TurnSummary.tool_calls). The old branch was dead code so the
    GoalChecker received an empty `tool_calls_made` list every turn,
    triggering false "zero successful tool calls" refusals on the
    matrix's 5 tool-dispatch cases (E1/E2/E4/C1/C3). The worker now
    reads from the canonical `span` events instead. See
    app/services/agentic_worker.py:180.
    """
    records = [
        _tool_call_span(
            tool_name="kaos-pdf-extract",
            call_id="a",
            is_error=False,
            result_summary="extracted 12 pages from doc.pdf",
        ),
        _tool_call_span(
            tool_name="kaos-content-search",
            call_id="b",
            is_error=False,
            result_summary="3 matches for 'governing law'",
        ),
        _sse("turn_summary", cost_usd=0.005),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents"],
        thinking_note="",
        iteration=1,
    )

    assert len(result.tool_calls_made) == 2
    assert {tc["tool_name"] for tc in result.tool_calls_made} == {
        "kaos-pdf-extract",
        "kaos-content-search",
    }
    # Per-row GoalChecker-contract keys must all be present.
    assert {tc["name"] for tc in result.tool_calls_made} == {
        "kaos-pdf-extract",
        "kaos-content-search",
    }
    for tc in result.tool_calls_made:
        assert tc["is_error"] is False
        assert isinstance(tc["summary_excerpt"], str)
        assert tc["summary_excerpt"]  # non-empty


async def test_tool_call_summary_excerpt_normalized_for_goal_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each row in tool_calls_made carries the GoalChecker contract keys.

    Regression for #548. The GoalCheckerSignature at
    kaos_agents/planning/goal_check.py:483-489 documents the dict
    shape as ``{name, is_error, summary_excerpt}`` and its rules at
    lines 343/410/430 pattern-match on `is_error=false`
    specifically. The SPA worker must emit those exact keys or the
    LLM critic concludes "tool_calls_made is empty" even when N
    tools succeeded — root cause of every WU-K v2 tool-dispatch
    failure.
    """
    records = [
        _tool_call_span(
            tool_name="kaos-web-search",
            call_id="c1",
            is_error=False,
            result_summary="10 results for 'SEC enforcement 2025'",
        ),
        _sse("turn_summary", cost_usd=0.005),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=_meta(),
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["web"],
        thinking_note="",
        iteration=1,
    )

    assert len(result.tool_calls_made) == 1
    row = result.tool_calls_made[0]
    # The three contract keys the GoalCheckerSignature pattern-matches on.
    assert row["name"] == "kaos-web-search"
    assert row["is_error"] is False
    assert row["summary_excerpt"].startswith("10 results")


async def test_tool_call_error_status_normalized_for_goal_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errored tool calls land with is_error=True (not is_error=false).

    Tests the inverse path of the previous test: when the tool
    span's `attributes.is_error` is True (e.g. anti-bot 403 from
    sec.gov), the normalized row must carry `is_error=True` so the
    critic correctly classifies it as a failure rather than a
    success. Regression for the E1/E2 SEC-RIA cases where the
    critic over-refused on partial-fetch-coverage tool runs.
    """
    records = [
        _tool_call_span(
            tool_name="kaos-web-fetch-page",
            call_id="c1",
            is_error=True,
            result_summary="403 Forbidden from sec.gov",
        ),
        _tool_call_span(
            tool_name="kaos-web-search",
            call_id="c2",
            is_error=False,
            result_summary="5 results found",
        ),
        _sse("turn_summary", cost_usd=0.003),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=_meta(),
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["web"],
        thinking_note="",
        iteration=1,
    )

    assert len(result.tool_calls_made) == 2
    by_name = {tc["name"]: tc for tc in result.tool_calls_made}
    assert by_name["kaos-web-fetch-page"]["is_error"] is True
    assert by_name["kaos-web-search"]["is_error"] is False


async def test_span_start_phase_is_ignored_only_complete_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`span` events with phase=start are not pushed into tool_calls_made.

    The worker should only record completed tool calls (those carry
    `is_error` + `result_summary`). Start-phase spans only carry
    tool_name + call_id; counting them would double-count and the
    GoalChecker would see ambiguous duplicates.
    """
    records = [
        _tool_call_span(tool_name="kaos-pdf-extract", call_id="a", phase="start"),
        _tool_call_span(
            tool_name="kaos-pdf-extract",
            call_id="a",
            is_error=False,
            result_summary="ok",
            phase="complete",
        ),
        _sse("turn_summary", cost_usd=0.001),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=_meta(),
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=["documents"],
        thinking_note="",
        iteration=1,
    )

    assert len(result.tool_calls_made) == 1
    assert result.tool_calls_made[0]["name"] == "kaos-pdf-extract"


async def test_cost_prefers_turn_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _sse("usage_observed", cost_usd=0.001),
        _sse("usage_observed", cost_usd=0.002),
        _sse("turn_summary", cost_usd=0.010),  # authoritative aggregate
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=1,
    )

    assert result.cost_usd == pytest.approx(0.010)


async def test_cost_falls_back_to_usage_sum_when_no_turn_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the upstream terminates early without a turn_summary (eg.
    network drop), sum the usage_observed events instead of reporting 0.
    """
    records = [
        _sse("usage_observed", cost_usd=0.003),
        _sse("usage_observed", cost_usd=0.004),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=1,
    )

    assert result.cost_usd == pytest.approx(0.007)


async def test_events_list_preserves_wire_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _sse("text_delta", content="hi"),
        _sse("turn_summary", cost_usd=0.0),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=1,
    )

    # Verbatim — same dicts, same order. A streaming worker forwards
    # these LIVE (not via WorkerResult.events, which stays empty so the
    # orchestrator doesn't replay them); the wire shape is sacred.
    assert _events == records
    assert result.events == []


async def test_malformed_payloads_do_not_crash_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {"event": "garbage", "data": "this is not json"},
        {"event": "missing_data"},  # no 'data' key at all
        _sse("text_delta", content="ok"),
        _sse("turn_summary", cost_usd=0.001),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=1,
    )

    # Malformed events still ride through the live stream so the SSE
    # consumer sees the full upstream trace; text + cost accounting
    # just skips them.
    assert result.text == "ok"
    assert result.cost_usd == pytest.approx(0.001)
    assert len(_events) == 4


async def test_worker_tolerates_extra_kwargs_from_future_loop_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward-compat — a newer AgenticLoop may pass more kwargs;
    the worker accepts and ignores them.
    """
    fake = _stream_chat_stub([_sse("turn_summary", cost_usd=0.0)])
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    meta = _meta()
    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=meta,
        max_cost_usd=0.10,
    )
    _events, result = await _run_worker(
        worker,
        user_message="hi",
        allowed_groups=[],
        thinking_note="",
        iteration=1,
        future_unknown_kwarg=object(),
    )

    assert result.text == ""


async def test_streams_records_live_then_terminal_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker is a streaming async generator: it yields each upstream
    SSE record verbatim (live, in order) plus a synthetic cost_forecast,
    and yields the aggregate WorkerResult as its FINAL item."""
    records = [
        _sse("text_delta", content="hi"),
        _sse("usage_observed", cost_usd=0.002),
        _sse("turn_summary", cost_usd=0.01),
    ]
    fake = _stream_chat_stub(records)
    monkeypatch.setattr(stream_proxy, "stream_chat", fake)
    monkeypatch.setattr(agentic_worker, "stream_chat", fake)

    worker = agentic_worker.make_worker(
        client=_client(),
        bearer_token="t",
        meta=_meta(),
        max_cost_usd=0.10,
    )
    items = [
        item
        async for item in worker(
            user_message="hi",
            allowed_groups=[],
            thinking_note="",
            iteration=1,
        )
    ]

    # Terminal item is the aggregate; everything before it is a live dict.
    assert isinstance(items[-1], WorkerResult)
    assert all(isinstance(it, dict) for it in items[:-1])
    # The upstream records were forwarded verbatim, in order (the synthetic
    # cost_forecast is interleaved live, so filter it out for this check).
    forwarded = [it for it in items[:-1] if it.get("event") != "cost_forecast"]
    assert forwarded == records
    # A synthetic cost_forecast was injected live, right after the
    # usage_observed it forecasts from.
    forecasts = [it for it in items[:-1] if it.get("event") == "cost_forecast"]
    assert len(forecasts) == 1
    assert items.index(forecasts[0]) == items.index(records[1]) + 1
    # The terminal WorkerResult carries the aggregate; events stay empty
    # (already streamed) so the orchestrator does not replay them.
    assert items[-1].text == "hi"
    assert items[-1].cost_usd == pytest.approx(0.01)
    assert items[-1].events == []
