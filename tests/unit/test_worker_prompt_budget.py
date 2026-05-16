"""Token-budget contract for the worker system prompt.

Implements §6.3 of `kaos-modules/docs/plans/thin-worker-prompt.md`.

The kaos-ui worker prompt is supposed to carry ONLY context — today's
date and the session voice. The tool catalog reaches the LLM via the
provider's native tool-use API (M5 of the plan), and behavior policy
(which tools to use, when to search, when to escalate) belongs to the
kaos-agents Signature decision points (TurnToolPolicy planner +
GoalChecker critic). Neither belongs in this prompt.

These tests are the mechanical guard against the prompt accidentally
regrowing 400 tokens of English behavior rules — the failure mode
that produced the 2026-05-16 dumpster fire. If a future contributor
adds an imperative rule, a hardcoded tool name, or re-inlines the
catalog into `kaos_ui.agents.augment_instructions`, one of these
tests fails.

Tokens are approximated via ``len(text) / 4`` (the kaos-agents
convention from ``KAOS_AGENT_CHARS_PER_TOKEN=4.0``). Cheap and
sufficient for a budget check.
"""

from __future__ import annotations

import pytest

from kaos_ui.agents import augment_instructions

# Char→token ratio kaos-agents uses for budget estimation.
CHARS_PER_TOKEN = 4.0


def _estimate_tokens(text: str) -> float:
    return len(text) / CHARS_PER_TOKEN


# Sample tool-name pool used by the anti-goal "no inline tool names"
# checks. These names must NOT appear in the rendered prompt — the
# native tool-use API is the source of truth.
_SAMPLE_TOOL_NAMES = (
    "kaos-source-fetch-url",
    "kaos-source-edgar-search",
    "kaos-content-search-document",
    "kaos-pdf-extract-page-text",
    "kaos-core-vfs-read",
    "kaos-citations-extract",
)

# Typical user-facing system prompt under the thin-worker-prompt
# refactor — identity + voice only. ~30 tokens. The tool catalog is
# delivered via the provider's native tool-use API (M5), not by
# augment_instructions; behavior rules are NOT in this string.
_REALISTIC_BASE = (
    "You are Kelvin, a meticulous legal-research assistant. Use the "
    "tools available in this session to answer the user's question; "
    "cite the source filename or URL for any fact you report."
)


# ─── Budget contracts (§6.3 of thin-worker-prompt.md) ─────────────────


def test_worker_prompt_under_budget_with_tools_no_corpus() -> None:
    """Steady-state worker prompt (tools enabled, no files attached)
    must fit in 300 tokens.

    Composition: `_date_preamble()` (~75 tok) + `base_prompt` (~30 tok
    after the thin-prompt refactor) ≈ ~105 tokens. Budget of 300
    leaves slack for prompt-tuning iterations but is tight enough to
    catch any catalog re-inlining or behavior-rule regrowth.

    M1+M5 of `thin-worker-prompt.md` shrink the prompt from ~1,600
    tokens (which included ~500 tokens of catalog + ~400 tokens of
    English rules) to ~105 tokens of pure context. If a future
    contributor adds behavior rules in English or re-inlines the
    catalog, this test fails first.
    """
    rendered = augment_instructions(base_prompt=_REALISTIC_BASE, tools_enabled=True)
    tokens = _estimate_tokens(rendered)
    assert tokens <= 300, (
        f"Worker prompt is {tokens:.0f} tokens (budget: 300). "
        "If you just added text to augment_instructions, ask whether "
        "the rule belongs in a kaos-agents Signature docstring instead. "
        "See kaos-modules/docs/plans/thin-worker-prompt.md §5 — "
        "anti-goals."
    )


def test_worker_prompt_under_budget_tools_disabled() -> None:
    """Tools-disabled branch must stay tiny — date + base + a single
    refusal sentence."""
    rendered = augment_instructions(
        base_prompt=_REALISTIC_BASE,
        tools_enabled=False,
    )
    tokens = _estimate_tokens(rendered)
    assert tokens <= 300, (
        f"Tools-disabled worker prompt is {tokens:.0f} tokens "
        "(budget: 300). Tools-disabled is the smallest composition "
        "path; if it's grown, behavior policy has crept in."
    )


def test_worker_prompt_has_date_preamble() -> None:
    """The date preamble is the one piece of dynamic context we DO
    want at the top of every prompt. Regression guard against B13
    (the agent confidently said "we are in 2024-2025; 2026 hasn't
    occurred yet" because the date wasn't in the prompt).
    """
    rendered = augment_instructions(base_prompt=_REALISTIC_BASE, tools_enabled=True)
    assert "## TODAY IS" in rendered
    # Trust-the-date directive must accompany the marker — the model
    # otherwise defaults to its training-cutoff perception of "now".
    assert "Trust this date" in rendered


# ─── Anti-goal contracts (§5 of thin-worker-prompt.md) ────────────────


@pytest.mark.parametrize(
    "forbidden_substring,reason",
    [
        (
            "Search-before-answer rule",
            "Behavior rule duplicating the planner Signature. "
            "Move to `_TurnToolPolicySignature` docstring instead.",
        ),
        (
            "Search-before-clarify",
            "Behavior rule duplicating the critic Signature. "
            "Move to `_GoalCheckerSignature` docstring instead.",
        ),
        (
            "kaos-source-fetch-url",
            "Hardcoded tool name in worker prompt. Tool names rot when "
            "the registry changes; let the catalog be the source of truth.",
        ),
        (
            "kaos-source-edgar-search",
            "Hardcoded tool name in worker prompt — same reason.",
        ),
        (
            "kaos-content-search-document",
            "Hardcoded tool name in worker prompt — same reason.",
        ),
        (
            "kaos-pdf-extract-page-text",
            "Hardcoded tool name in worker prompt — same reason.",
        ),
        (
            "your FIRST action MUST",
            "Imperative behavior rule. Move to a Signature docstring or "
            "thread via `thinking_note` from the critic's `next_action`.",
        ),
        (
            "Never answer factual lookups",
            "Behavior rule. The GoalChecker handles this — it returns "
            "`needs_more_work` when the agent answered without tools.",
        ),
        (
            "CALL THE TOOLS to search them BEFORE",
            "Behavior rule. The GoalChecker handles this.",
        ),
    ],
)
def test_worker_prompt_does_not_carry_behavior_rule(forbidden_substring: str, reason: str) -> None:
    """Concrete anti-goal check.

    Each entry is a phrase that has appeared in the worker prompt and
    been deleted as part of the thin-worker-prompt refactor. If a
    future PR reintroduces one, this test fails with a pointer to the
    right Signature instead.

    See `kaos-modules/docs/plans/thin-worker-prompt.md` §5 for the
    full list and §2.5 for the kaos-ui-hack ↔ kaos-agents-Signature
    mapping.
    """
    rendered = augment_instructions(base_prompt=_REALISTIC_BASE, tools_enabled=True)
    assert forbidden_substring not in rendered, (
        f"Worker prompt contains forbidden substring "
        f"{forbidden_substring!r}.\nReason: {reason}\n"
        "See kaos-modules/docs/plans/thin-worker-prompt.md §5."
    )


def test_worker_prompt_does_not_inline_tool_names() -> None:
    """No tool name should appear in the rendered prompt.

    Under M5, kaos-agents delivers tool definitions to the LLM via
    the provider's native tool-use API (kaos-llm-core ReAct passes
    ``tools=`` to ``chat_async``). The system prompt is for context
    (date, voice) — never for the catalog. Regression guard against
    re-inlining the catalog block.
    """
    rendered = augment_instructions(base_prompt=_REALISTIC_BASE, tools_enabled=True)
    for name in _SAMPLE_TOOL_NAMES:
        count = rendered.count(name)
        assert count == 0, (
            f"Tool name {name!r} appears {count}x in the worker prompt. "
            "Under M5 of the thin-worker-prompt plan the catalog is "
            "delivered via the provider's native tool-use API, not via "
            "the system prompt. See "
            "kaos-modules/docs/plans/thin-worker-prompt.md §4.5."
        )
