"""Tests for R2.3 — cost telemetry aggregates all critics + planner.

Pre-R2.3 (kaos-modules/docs/plans/2026-05-21-reliability-roadmap.md § R2.3),
``TurnUsageRecorder.snapshot()`` preferred ``turn_summary.cost_usd``
(per-WORKER-iteration aggregate) over the running ``usage_observed`` sum.
On critic-heavy turns this under-counted by 5-6x because GoalCheck / M2 /
M3 / planner LLM calls fire OUTSIDE the worker's ``turn_summary`` and
their cost ended up discarded.

Post-R2.3, the recorder also observes ``loop_terminated.cost_usd`` (the
orchestrator's authoritative aggregate, mirroring
``state.cumulative_cost_usd`` in kaos-agents) and prefers it over both
the per-iteration ``turn_summary`` and the ``usage_observed`` running
sum. When ``loop_terminated`` doesn't arrive, falls back to the
``usage_observed`` sum (which captures critic + planner cost). The
last-resort fallback is the legacy ``turn_summary`` value.
"""

from __future__ import annotations

from app.services.tool_call_recorder import TurnUsageRecorder


class TestPreloopTerminatedAggregate:
    """``loop_terminated.cost_usd`` is the authoritative aggregate."""

    def test_loop_terminated_wins_over_turn_summary(self):
        """When both events fire, prefer loop_terminated."""
        r = TurnUsageRecorder()
        # Worker iteration 1: chat agent spent $0.001 on respond text.
        r.observe("turn_summary", {"cost_usd": 0.001, "total_tokens": 100})
        # Orchestrator's goal_check / M2 / M3 / planner usage_observed
        # events fire between iterations.
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0015, "input_tokens": 30, "output_tokens": 20, "source": "goal_check"},
        )
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0009, "input_tokens": 20, "output_tokens": 15, "source": "m2_critic"},
        )
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0007, "input_tokens": 15, "output_tokens": 10, "source": "planner"},
        )
        # Loop terminator: aggregates everything (worker + critics + planner).
        r.observe("loop_terminated", {"cost_usd": 0.0041, "reason": "satisfied"})

        cost, tokens = r.snapshot()
        # loop_terminated is preferred — its 0.0041 reflects the
        # authoritative orchestrator aggregate.
        assert abs(cost - 0.0041) < 1e-9
        # tokens come from the running usage_observed sum because
        # LoopTerminated doesn't ship tokens.
        assert tokens == 30 + 20 + 20 + 15 + 15 + 10  # 110

    def test_loop_terminated_alone_works(self):
        """Even with no per-call usage_observed events, loop_terminated alone works."""
        r = TurnUsageRecorder()
        r.observe("loop_terminated", {"cost_usd": 0.05})
        cost, tokens = r.snapshot()
        assert cost == 0.05
        assert tokens == 0


class TestUsageSumFallback:
    """When loop_terminated is absent, prefer usage_observed sum over turn_summary."""

    def test_usage_sum_includes_critic_costs_when_loop_terminated_missing(self):
        """The Agent 5 diary pathology: critic-heavy turn, no loop_terminated.

        Pre-R2.3 the recorder returned turn_summary's $0.001 (worker
        only). Post-R2.3 it returns the usage_observed sum which
        includes critic + planner costs.
        """
        r = TurnUsageRecorder()
        # Worker iteration's turn_summary aggregate (worker LLM calls only).
        r.observe("turn_summary", {"cost_usd": 0.0014, "total_tokens": 200})
        # Critic + planner events with realistic costs.
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0014, "input_tokens": 80, "output_tokens": 60, "source": "worker"},
        )
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0025, "input_tokens": 30, "output_tokens": 20, "source": "goal_check"},
        )
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0030, "input_tokens": 25, "output_tokens": 18, "source": "m2_critic"},
        )
        r.observe(
            "usage_observed",
            {"cost_usd": 0.0022, "input_tokens": 20, "output_tokens": 15, "source": "planner"},
        )

        cost, _tokens = r.snapshot()
        # Sum of all four usage_observed events = 0.0091
        assert abs(cost - 0.0091) < 1e-9
        # Spot-check that this is the "true $0.0091 aggregate" the R2.3
        # spec explicitly cites.
        assert cost > 5 * 0.0014, "post-R2.3 must escape the 5-6x under-count"


class TestTurnSummaryFallback:
    """Last-resort: only turn_summary, no usage_observed or loop_terminated."""

    def test_turn_summary_alone_works(self):
        """Pre-existing legacy case: turn_summary is the only thing we see."""
        r = TurnUsageRecorder()
        r.observe("turn_summary", {"cost_usd": 0.005, "total_tokens": 500})
        cost, tokens = r.snapshot()
        assert cost == 0.005
        assert tokens == 500

    def test_empty_recorder_returns_zero(self):
        """No events observed → (0.0, 0)."""
        r = TurnUsageRecorder()
        cost, tokens = r.snapshot()
        assert cost == 0.0
        assert tokens == 0


class TestMalformedPayloadsDoNotCrash:
    """Defensive: malformed payloads don't crash the recorder."""

    def test_non_dict_payload_ignored(self):
        r = TurnUsageRecorder()
        r.observe("usage_observed", "not a dict")
        r.observe("turn_summary", 42)
        r.observe("loop_terminated", None)
        cost, tokens = r.snapshot()
        assert cost == 0.0
        assert tokens == 0

    def test_missing_cost_field_ignored(self):
        r = TurnUsageRecorder()
        r.observe("turn_summary", {"total_tokens": 100})  # no cost
        r.observe("usage_observed", {"input_tokens": 10})  # no cost
        r.observe("loop_terminated", {})  # no cost
        cost, tokens = r.snapshot()
        # Only the input_tokens field survived from the usage_observed event.
        assert cost == 0.0
        assert tokens == 10  # input only

    def test_wrong_cost_type_ignored(self):
        r = TurnUsageRecorder()
        r.observe("usage_observed", {"cost_usd": "not a number", "input_tokens": 10})
        cost, tokens = r.snapshot()
        assert cost == 0.0
        assert tokens == 10  # input only

    def test_unknown_event_name_ignored(self):
        r = TurnUsageRecorder()
        r.observe("intent_classified", {"cost_usd": 99.0})
        r.observe("text_delta", {"content": "hi"})
        cost, tokens = r.snapshot()
        assert cost == 0.0
        assert tokens == 0
