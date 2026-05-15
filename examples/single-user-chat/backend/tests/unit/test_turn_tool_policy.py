"""TR-5 — TurnToolPolicy planner unit tests.

We stub ``Call.invoke`` rather than hit a real provider because:
  - Unit tests must not require network/credentials.
  - The Program's contract is what we want to pin: input → output
    intersection with ceiling, fall-back-on-low-confidence semantics,
    fall-back-on-exception semantics.

The integration of this Program with a real LLM is covered by TR-11's
live tests, gated on provider credentials being available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest

from app.services.turn_tool_policy import (
    TurnToolPolicy,
    TurnToolPolicyResult,
    plan_turn_tool_policy,
)

pytestmark = pytest.mark.unit


@dataclass
class _FakeUsage:
    cost_usd: float = 0.0001


@dataclass
class _FakeOutput:
    policy: TurnToolPolicyResult


@dataclass
class _FakeInvocation:
    output: _FakeOutput
    usage: _FakeUsage


def _stub_invoke(policy: TurnToolPolicyResult, cost_usd: float = 0.0001) -> Any:
    """Patchable replacement for ``Call.invoke`` returning a fixed
    policy. Method signature: ``self`` is the bound Call instance.
    """

    async def _impl(self: Any, **_kwargs: Any) -> _FakeInvocation:
        return _FakeInvocation(
            output=_FakeOutput(policy=policy), usage=_FakeUsage(cost_usd=cost_usd)
        )

    return _impl


# ── happy path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_narrowed_groups_when_planner_is_confident() -> None:
    """Confident planner output passes through unmodified (subset only)."""
    stub = TurnToolPolicyResult(
        turn_groups=["documents", "citations"],
        reasoning="The user is asking about an uploaded contract.",
        confidence=0.85,
    )
    with patch("kaos_llm_core.Call.invoke", new=_stub_invoke(stub)):
        policy = await plan_turn_tool_policy(
            user_message="What does section 7 of the PDF say?",
            recent_turns="",
            corpus_headlines="contract.pdf — 250kb, application/pdf",
            ceiling_groups=["documents", "citations", "vfs", "web"],
            available_groups=["documents", "citations", "vfs", "web"],
        )

    assert isinstance(policy, TurnToolPolicy)
    assert policy.turn_groups == frozenset({"documents", "citations"})
    assert policy.fell_back_to_ceiling is False
    assert policy.confidence == 0.85
    assert "uploaded contract" in policy.reasoning


# ── low confidence ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_falls_back_to_ceiling_on_low_confidence() -> None:
    """Below the threshold, the planner's narrowing is discarded."""
    stub = TurnToolPolicyResult(
        turn_groups=["documents"],
        reasoning="Maybe documents?",
        confidence=0.4,
    )
    with patch("kaos_llm_core.Call.invoke", new=_stub_invoke(stub)):
        policy = await plan_turn_tool_policy(
            user_message="hi",
            recent_turns="",
            corpus_headlines="",
            ceiling_groups=["documents", "citations", "vfs"],
            available_groups=["documents", "citations", "vfs", "web"],
        )

    assert policy.turn_groups == frozenset({"documents", "citations", "vfs"})
    assert policy.fell_back_to_ceiling is True
    assert "confidence" in policy.reasoning.lower()


# ── ceiling intersection ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intersects_with_ceiling_even_when_confident() -> None:
    """A confident planner that suggests an out-of-ceiling group only
    gets its in-ceiling subset honored.
    """
    stub = TurnToolPolicyResult(
        turn_groups=["documents", "web"],  # `web` NOT in ceiling
        reasoning="documents for the PDF, web for live data",
        confidence=0.9,
    )
    with patch("kaos_llm_core.Call.invoke", new=_stub_invoke(stub)):
        policy = await plan_turn_tool_policy(
            user_message="research the PDF and look up live SEC data",
            recent_turns="",
            corpus_headlines="filing.pdf",
            ceiling_groups=["documents", "citations", "vfs"],  # no `web`
            available_groups=["documents", "citations", "vfs", "web"],
        )

    assert policy.turn_groups == frozenset({"documents"})
    assert policy.fell_back_to_ceiling is False


# ── empty intersection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_intersection_falls_back_to_full_ceiling() -> None:
    """When the planner picks ONLY out-of-ceiling groups, fall back."""
    stub = TurnToolPolicyResult(
        turn_groups=["web"],  # not in ceiling at all
        reasoning="just web",
        confidence=0.95,
    )
    with patch("kaos_llm_core.Call.invoke", new=_stub_invoke(stub)):
        policy = await plan_turn_tool_policy(
            user_message="search EDGAR",
            recent_turns="",
            corpus_headlines="",
            ceiling_groups=["documents", "citations", "vfs"],
            available_groups=["documents", "citations", "vfs", "web"],
        )

    assert policy.turn_groups == frozenset({"documents", "citations", "vfs"})
    assert policy.fell_back_to_ceiling is True


# ── empty ceiling short-circuit ──────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_ceiling_short_circuits_without_llm_call() -> None:
    """When the session has tools fully disabled, the planner doesn't
    burn a Haiku call; returns an empty policy immediately."""

    async def _should_not_be_called(self: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Call.invoke must not run when ceiling is empty")

    with patch("kaos_llm_core.Call.invoke", new=_should_not_be_called):
        policy = await plan_turn_tool_policy(
            user_message="anything",
            recent_turns="",
            corpus_headlines="",
            ceiling_groups=[],
            available_groups=["documents", "citations", "vfs", "web"],
        )

    assert policy.turn_groups == frozenset()
    assert policy.fell_back_to_ceiling is False
    assert policy.cost_usd == 0.0


# ── exception handling ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exception_falls_back_to_full_ceiling() -> None:
    """Provider error / timeout / parser failure → ceiling, not crash."""

    async def _boom(self: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("provider rate limit hit")

    with patch("kaos_llm_core.Call.invoke", new=_boom):
        policy = await plan_turn_tool_policy(
            user_message="search for SEC filings",
            recent_turns="",
            corpus_headlines="",
            ceiling_groups=["documents", "web"],
            available_groups=["documents", "citations", "vfs", "web"],
        )

    assert policy.turn_groups == frozenset({"documents", "web"})
    assert policy.fell_back_to_ceiling is True
    assert policy.confidence == 0.0
    assert "rate limit" in policy.reasoning.lower()


# ── threshold override ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_caller_threshold_override_takes_effect() -> None:
    """Caller can lower the threshold to accept lower-confidence
    narrowing (eg. when the user explicitly opts into aggressive
    narrowing for cost reasons)."""
    stub = TurnToolPolicyResult(
        turn_groups=["documents"],
        reasoning="probably documents",
        confidence=0.55,
    )
    with patch("kaos_llm_core.Call.invoke", new=_stub_invoke(stub)):
        policy = await plan_turn_tool_policy(
            user_message="read it",
            recent_turns="",
            corpus_headlines="x.pdf",
            ceiling_groups=["documents", "citations", "vfs"],
            available_groups=["documents", "citations", "vfs"],
            confidence_threshold=0.5,  # lower than default 0.6
        )

    # 0.55 > 0.5 → planner output is honored.
    assert policy.turn_groups == frozenset({"documents"})
    assert policy.fell_back_to_ceiling is False
