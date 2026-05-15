"""TR-5 — Dynamic per-turn tool-category planner.

The TurnToolPolicy Program runs BEFORE each ReAct turn and narrows the
SessionMeta.tool_set ceiling to just the categories this specific
message needs. The chat router (TR-6) intersects the planner's output
with the user's ceiling and hands the result to the proxy filter
(TR-2).

Why this exists:
  - Users set a generous ceiling once ("documents, citations, vfs,
    web") and want the agent to pick the right subset per turn —
    web for research questions, documents for upload questions.
  - Sending a 65-tool catalog to the LLM on every turn is wasteful;
    a narrowed list improves tool-selection accuracy and saves
    ~5-15c per turn on prompt tokens.
  - The planner is a Haiku-class LLM call. Target budget: ≤ $0.0002
    per turn, ≤ 300ms p95. When the planner is uncertain
    (``confidence < threshold``), we abdicate and use the full
    ceiling — refusing to narrow is always safe.

Lives in single-user-chat for two release windows of battle-testing
before promotion into ``kaos_agents.planning.policy`` so other
consumers can share it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from kaos_llm_core import Call, InputField, OutputField, Signature
from pydantic import BaseModel, Field

from app.logging_setup import app_logger

logger = app_logger("turn_tool_policy")

_BASELINE_PLANNER_MODEL = "anthropic:claude-haiku-4-5"


def _resolve_planner_model() -> str:
    """Read the planner model from AppSettings at call time so the
    ``APP_TURN_POLICY_MODEL`` env override takes effect per turn.
    """
    from app.settings import AppSettings

    return AppSettings().turn_policy_model


def _resolve_confidence_threshold() -> float:
    """Below this confidence the planner abdicates and the chat router
    uses the full ceiling. Defaults to 0.6 — tuned in the prompt
    examples so high-recall scenarios (uploaded files + ambiguous
    question) trip back to the ceiling rather than narrow.
    """
    from app.settings import AppSettings

    return AppSettings().turn_policy_confidence_threshold


# ── result type ──────────────────────────────────────────────────────


class TurnToolPolicyResult(BaseModel):
    """Structured planner output. JSON-serializable for SSE wire (TR-7)."""

    turn_groups: list[str] = Field(
        description=(
            "Tool category ids the agent should have for this turn — "
            "the planner's narrowed view of the ceiling."
        )
    )
    reasoning: str = Field(
        description="One sentence justifying the choice. Surfaced to the user.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Planner's self-rated confidence in its narrowing."
    )


# ── final policy returned to the chat router ─────────────────────────


@dataclass(frozen=True, slots=True)
class TurnToolPolicy:
    """The chat router consumes this — already intersected with the
    ceiling and with fell-back semantics applied.

    Frozen + slotted to match kaos-llm-core's value-type conventions.
    """

    turn_groups: frozenset[str]
    reasoning: str
    confidence: float
    fell_back_to_ceiling: bool
    cost_usd: float
    latency_ms: float


# ── signature ────────────────────────────────────────────────────────


class _TurnToolPolicySignature(Signature):
    """Pick the smallest set of tool groups that can answer the user's
    message.

    Rules:
    - Output ``turn_groups`` MUST be a subset of ``ceiling_groups``.
      The user has explicitly disabled any group not in the ceiling;
      adding one would be a security policy violation.
    - When in doubt, output the full ceiling. False narrowing
      (dropping a category the agent actually needed) costs the user
      a wasted turn; false broadening costs at most a few cents of
      prompt tokens. Asymmetric — prefer broad.
    - ``confidence`` is your own self-rated [0, 1]. Output <0.6 when
      the message is ambiguous, terse ("hi", "yes"), or could
      plausibly need any group.
    - ``reasoning`` is one short sentence the user will see as a
      transparency badge ("Web for the SEC search").

    Decision shortcuts:
    - User mentions a website, government source, "search", "live",
      "lookup", or asks about a recent event → likely needs ``web``.
    - User refers to an uploaded file, PDF, contract, or "the
      document" → likely needs ``documents``.
    - User asks for legal/financial citations or wants a Bluebook /
      W. Trans. cite → likely needs ``citations``.
    - User asks to inspect / list / read raw files → likely needs
      ``vfs``.
    - Short greeting, clarification, or pure language question →
      narrow to zero groups + low confidence so the router falls
      back to the ceiling.
    """

    user_message: str = InputField(description="The user message starting this turn.")
    recent_turns: str = InputField(
        description=(
            "Last 3-5 conversation turns compressed to one line each. Empty string when no history."
        )
    )
    corpus_headlines: str = InputField(
        description=(
            "One line per uploaded file: 'filename — size, content_type'. "
            "Empty string when nothing uploaded."
        )
    )
    ceiling_groups: list[str] = InputField(
        description=("The session's allowed tool groups — your output is bounded by this set."),
    )
    available_groups: list[str] = InputField(
        description="All tool groups known to the runtime, for context."
    )
    policy: TurnToolPolicyResult = OutputField(
        description=(
            "Narrowed tool-group selection for this specific turn, with "
            "self-rated confidence and a one-sentence reasoning."
        )
    )


# ── public entrypoint ────────────────────────────────────────────────


async def plan_turn_tool_policy(
    *,
    user_message: str,
    recent_turns: str,
    corpus_headlines: str,
    ceiling_groups: list[str],
    available_groups: list[str],
    model: str | None = None,
    confidence_threshold: float | None = None,
) -> TurnToolPolicy:
    """Run the planner and return a :class:`TurnToolPolicy`.

    The planner is best-effort. On any exception (provider error,
    timeout, parser failure) we return ``fell_back_to_ceiling=True``
    with ``turn_groups = frozenset(ceiling_groups)`` so the agent
    still gets a useful tool catalog.

    Empty ceiling → no planner call. The chat layer treats the empty
    ceiling as "tools disabled for this session" and the planner has
    nothing meaningful to narrow within. Returns the empty policy
    immediately so we don't burn a Haiku call on a deterministic
    answer.
    """
    if not ceiling_groups:
        return TurnToolPolicy(
            turn_groups=frozenset(),
            reasoning="Tools disabled for this session.",
            confidence=1.0,
            fell_back_to_ceiling=False,
            cost_usd=0.0,
            latency_ms=0.0,
        )

    used_model = model or _resolve_planner_model()
    threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else _resolve_confidence_threshold()
    )
    call = Call(_TurnToolPolicySignature, model=used_model)
    t_start = time.monotonic()
    try:
        invocation = await call.invoke(
            user_message=user_message,
            recent_turns=recent_turns,
            corpus_headlines=corpus_headlines,
            ceiling_groups=ceiling_groups,
            available_groups=available_groups,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - t_start) * 1000
        logger.warning("TurnToolPolicy planner failed; falling back to ceiling. err=%s", exc)
        return TurnToolPolicy(
            turn_groups=frozenset(ceiling_groups),
            reasoning=f"Planner unavailable: {exc}. Using full ceiling.",
            confidence=0.0,
            fell_back_to_ceiling=True,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )
    latency_ms = (time.monotonic() - t_start) * 1000
    raw = invocation.output.policy
    cost_usd = float(getattr(invocation.usage, "cost_usd", 0.0) or 0.0)

    # Intersect the planner's choice with the ceiling — defensive in
    # case the model emits an out-of-set group.
    ceiling_set = frozenset(ceiling_groups)
    chosen = frozenset(raw.turn_groups) & ceiling_set

    if raw.confidence < threshold or not chosen:
        # Low confidence OR planner chose nothing reachable → use the
        # full ceiling. Refusing to narrow is always safe.
        return TurnToolPolicy(
            turn_groups=ceiling_set,
            reasoning=(
                raw.reasoning + f" (planner confidence {raw.confidence:.2f} < {threshold:.2f}; "
                "expanded to ceiling)"
            ),
            confidence=raw.confidence,
            fell_back_to_ceiling=True,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

    return TurnToolPolicy(
        turn_groups=chosen,
        reasoning=raw.reasoning,
        confidence=raw.confidence,
        fell_back_to_ceiling=False,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )


__all__ = [
    "TurnToolPolicy",
    "TurnToolPolicyResult",
    "plan_turn_tool_policy",
]
