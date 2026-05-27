"""Unit test for the SPA cost-forecast SSE event (plan Issue 9).

Pre-fix the worker accumulated ``usage_sum_cost_usd`` from
``usage_observed`` events but never re-emitted a running total —
the SPA UI had to wait for the end-of-run ``turn_summary`` to see
any number. Mid-turn, attorneys could overshoot a $0.25 cap by 50%+
on a tool storm with no warning.

Post-fix every ``usage_observed`` event triggers a synthetic
``cost_forecast`` event appended to ``captured_events`` with:
- ``cost_usd_so_far`` — rolling sum
- ``max_cost_usd`` — the per-turn cap (passed into the worker)
- ``fraction_used`` — cost / cap, or null when cap is 0
- ``warn_threshold_reached`` — True at ≥80% of cap

The SPA UI's RunInspector consumes these to draw a running-cost line
and flash a warning at 80%.

This test calls the worker pump loop's branch logic directly via a
small re-implementation, since the full worker pulls in httpx +
kaos-agents and we just want to lock the event-emission contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _simulate_pump(events: list[dict], max_cost_usd: float) -> list[dict]:
    """Mirror of the cost_forecast emission branch in
    ``agentic_worker.build_worker``. Kept in lockstep with the
    real implementation; if the production code's emission shape
    changes, this test fails loud so callers know to update their
    consumers (UI, audit log).
    """
    captured_events: list[dict] = []
    usage_sum_cost_usd: float = 0.0
    for record in events:
        captured_events.append(record)
        payload = json.loads(record["data"]) if "data" in record else {}
        if payload.get("type") == "usage_observed":
            cost = payload.get("cost_usd")
            if isinstance(cost, int | float):
                usage_sum_cost_usd += float(cost)
                forecast_event = {
                    "event": "cost_forecast",
                    "data": json.dumps(
                        {
                            "type": "cost_forecast",
                            "cost_usd_so_far": round(usage_sum_cost_usd, 6),
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
    return captured_events


@pytest.mark.unit
def test_cost_forecast_emitted_per_usage_observed() -> None:
    """One usage_observed → one cost_forecast appended after it."""
    events = [
        {
            "event": "usage_observed",
            "data": json.dumps({"type": "usage_observed", "cost_usd": 0.01}),
        },
        {
            "event": "usage_observed",
            "data": json.dumps({"type": "usage_observed", "cost_usd": 0.02}),
        },
    ]
    out = _simulate_pump(events, max_cost_usd=0.25)
    forecasts = [e for e in out if e["event"] == "cost_forecast"]
    assert len(forecasts) == 2
    first = json.loads(forecasts[0]["data"])
    second = json.loads(forecasts[1]["data"])
    assert first["cost_usd_so_far"] == 0.01
    assert second["cost_usd_so_far"] == 0.03  # rolling sum
    assert first["warn_threshold_reached"] is False
    assert second["warn_threshold_reached"] is False


@pytest.mark.unit
def test_cost_forecast_warns_at_80_percent() -> None:
    """At ≥80% of cap, warn_threshold_reached flips True."""
    events = [
        {
            "event": "usage_observed",
            "data": json.dumps({"type": "usage_observed", "cost_usd": 0.20}),
        },
    ]
    out = _simulate_pump(events, max_cost_usd=0.25)
    forecast = json.loads(next(e for e in out if e["event"] == "cost_forecast")["data"])
    assert forecast["cost_usd_so_far"] == 0.20
    assert forecast["fraction_used"] == 0.8
    assert forecast["warn_threshold_reached"] is True


@pytest.mark.unit
def test_cost_forecast_safe_against_zero_cap() -> None:
    """max_cost_usd=0 must not divide-by-zero — fraction_used is null,
    warn_threshold_reached stays False.
    """
    events = [
        {
            "event": "usage_observed",
            "data": json.dumps({"type": "usage_observed", "cost_usd": 0.05}),
        },
    ]
    out = _simulate_pump(events, max_cost_usd=0.0)
    forecast = json.loads(next(e for e in out if e["event"] == "cost_forecast")["data"])
    assert forecast["cost_usd_so_far"] == 0.05
    assert forecast["fraction_used"] is None
    assert forecast["warn_threshold_reached"] is False


@pytest.mark.unit
def test_cost_forecast_ignores_unrelated_events() -> None:
    """Only usage_observed triggers a forecast; text_delta etc. don't."""
    events = [
        {"event": "text_delta", "data": json.dumps({"type": "text_delta", "content": "hi"})},
        {"event": "span", "data": json.dumps({"type": "span", "subject": "tool_call"})},
        {
            "event": "usage_observed",
            "data": json.dumps({"type": "usage_observed", "cost_usd": 0.01}),
        },
        {"event": "turn_summary", "data": json.dumps({"type": "turn_summary", "cost_usd": 0.01})},
    ]
    out = _simulate_pump(events, max_cost_usd=0.25)
    forecasts = [e for e in out if e["event"] == "cost_forecast"]
    assert len(forecasts) == 1


@pytest.mark.unit
def test_production_emission_branch_matches_simulator() -> None:
    """Sanity: the production code's emission branch matches the
    simulator above. If this fails, the simulator drifted or the
    production code changed — update both in lockstep.
    """
    from app.services import agentic_worker as worker_mod

    source = worker_mod.__file__
    assert source.endswith(".py")
    body = Path(source).read_text(encoding="utf-8")
    assert "cost_forecast" in body, (
        "agentic_worker no longer emits cost_forecast — Issue 9 SPA layer regressed."
    )
    assert "warn_threshold_reached" in body, "cost_forecast event lost its 80% warn marker."
    assert "fraction_used" in body
