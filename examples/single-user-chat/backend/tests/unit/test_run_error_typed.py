"""Unit tests for the typed ``error_category`` on the SPA's
``run_error`` SSE envelope (plan Issue 6 acceptance criterion).

Pre-fix the SPA emitted ``run_error`` with only ``what`` + ``how_to_fix``
free-text. The SPA UI couldn't distinguish budget-exceeded from
provider-5xx from grounding-refusal without string-grepping the
``what`` field — which is fragile and breaks the "Replay /
debug yesterday's turn" flow.

Post-fix every ``run_error`` carries ``error_category`` ∈
``RUN_ERROR_CATEGORIES``. This file locks the classifier contract.
The category vocabulary mirrors what the plan asks kaos-agents to
put on the ``RunError`` event (we'll ingest the upstream field once
kaos-agents 0.1.8+ ships it).
"""

from __future__ import annotations

import pytest

from app.services.stream_proxy import (
    RUN_ERROR_CATEGORIES,
    classify_upstream_error,
)


@pytest.mark.unit
def test_429_maps_to_provider_429() -> None:
    assert classify_upstream_error(429, "") == "provider_429"


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_5xx_maps_to_provider_5xx(status: int) -> None:
    assert classify_upstream_error(status, "") == "provider_5xx"


@pytest.mark.unit
def test_402_maps_to_budget() -> None:
    assert classify_upstream_error(402, "") == "budget"


@pytest.mark.unit
def test_budget_exceeded_body_maps_to_budget() -> None:
    """Application-layer BudgetExceeded surfaces as 4xx-other but the
    body string is the load-bearing signal. Match the kaos-llm-core
    exception class name verbatim.
    """
    assert (
        classify_upstream_error(400, "BudgetExceeded: limit $0.25 exceeded")
        == "budget"
    )


@pytest.mark.unit
def test_circuit_breaker_body_maps_to_circuit_breaker() -> None:
    assert (
        classify_upstream_error(400, "circuit breaker opened after 3 consecutive failures")
        == "circuit_breaker"
    )


@pytest.mark.unit
def test_tool_timeout_body_maps_to_tool_timeout() -> None:
    assert (
        classify_upstream_error(400, "Tool kaos-web-fetch hit timeout after 30s")
        == "tool_timeout"
    )


@pytest.mark.unit
def test_ungrounded_body_maps_to_grounding_refuse() -> None:
    assert (
        classify_upstream_error(400, "Refused: no_evidence in corpus")
        == "grounding_refuse"
    )


@pytest.mark.unit
def test_unknown_4xx_maps_to_internal() -> None:
    assert classify_upstream_error(400, "Some generic 4xx body") == "internal"


@pytest.mark.unit
def test_every_returned_category_is_in_vocabulary() -> None:
    """Defensive: the classifier must never invent a category that
    the SPA UI doesn't know how to render.
    """
    samples: list[tuple[int, str]] = [
        (429, ""),
        (500, ""),
        (503, ""),
        (402, ""),
        (400, "BudgetExceeded"),
        (400, "circuit breaker"),
        (400, "tool ... timeout"),
        (400, "no_evidence ungrounded"),
        (400, "anything else"),
    ]
    for status, body in samples:
        assert classify_upstream_error(status, body) in RUN_ERROR_CATEGORIES, (
            f"classifier returned out-of-vocab category for ({status}, {body!r})"
        )


@pytest.mark.unit
def test_vocabulary_includes_all_plan_categories() -> None:
    """Plan Issue 6 spec lists these seven categories. The literal
    must include every one — any drift here is a plan-vs-impl bug.
    """
    expected = {
        "budget",
        "provider_5xx",
        "provider_429",
        "tool_timeout",
        "grounding_refuse",
        "circuit_breaker",
        "internal",
    }
    assert set(RUN_ERROR_CATEGORIES) == expected
