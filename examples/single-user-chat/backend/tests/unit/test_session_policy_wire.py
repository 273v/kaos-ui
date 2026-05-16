"""Unit tests for :class:`app.models.SessionPolicyWire`.

Covers the wire shape itself — construction, round-trip with the
kaos-agents :class:`SessionPolicy` value type, and the persona-preset
factory. Migration scenarios live in test_session_tool_set_migration.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import SessionPolicyWire


def test_default_construction_matches_research_persona() -> None:
    """Field defaults mirror the research persona's allowed_groups +
    soft_ceiling — the 80% case for new sessions.
    """
    wire = SessionPolicyWire()

    expected_research = {
        "web",
        "browser",
        "netinfra",
        "documents",
        "citations",
        "vfs",
        "forensics",
        "retrieval",
    }
    assert set(wire.allowed_groups) == expected_research
    assert set(wire.soft_ceiling) == expected_research
    assert wire.persona == "research"
    assert wire.auto_narrow is True
    assert wire.auto_elevate is True
    assert wire.auto_loop is True


def test_loop_budget_defaults() -> None:
    """The three independent loop limiters carry the design-doc defaults
    (3 iterations / $0.25 / 60s)."""
    wire = SessionPolicyWire()
    assert wire.max_loop_iterations == 3
    assert wire.max_loop_cost_usd == pytest.approx(0.25)
    assert wire.max_loop_wall_clock_seconds == pytest.approx(60.0)


def test_denied_tools_default_includes_self_recursive_agents() -> None:
    """Recursion guard — the 4 kaos-agent-* tools must be denied by
    default so accidental opt-in to the ``agents`` group can't trigger
    infinite self-recursion."""
    wire = SessionPolicyWire()
    for forbidden in (
        "kaos-agent-chat",
        "kaos-agent-plan",
        "kaos-agent-findings",
        "kaos-agent-corpus-filter",
    ):
        assert forbidden in wire.denied_tools


def test_is_blocking_all_true_when_allowed_groups_empty() -> None:
    wire = SessionPolicyWire(allowed_groups=[])
    assert wire.is_blocking_all is True


def test_is_blocking_all_false_for_default() -> None:
    assert SessionPolicyWire().is_blocking_all is False


def test_for_persona_research_matches_default() -> None:
    wire = SessionPolicyWire.for_persona("research")
    default = SessionPolicyWire()
    assert set(wire.allowed_groups) == set(default.allowed_groups)
    assert set(wire.soft_ceiling) == set(default.soft_ceiling)
    assert wire.persona == "research"


def test_for_persona_drafting_adds_authoring_group() -> None:
    """The drafting persona widens the soft_ceiling with the
    ``authoring`` group (DOCX / PPTX / XLSX / PDF writers)."""
    wire = SessionPolicyWire.for_persona("drafting")
    assert "authoring" in wire.soft_ceiling
    assert "authoring" in wire.allowed_groups
    assert wire.persona == "drafting"


def test_for_persona_forensics_uses_tight_ceiling() -> None:
    """Per design plan §7.4 — forensics workflows stay in lane.
    Soft ceiling is exactly {forensics, vfs}; no web egress.
    """
    wire = SessionPolicyWire.for_persona("forensics")
    assert set(wire.soft_ceiling) == {"forensics", "vfs"}
    assert set(wire.allowed_groups) == {"forensics", "vfs"}
    assert wire.persona == "forensics"
    # No surprising web egress.
    for forbidden in ("web", "browser", "netinfra"):
        assert forbidden not in wire.soft_ceiling


def test_to_session_policy_round_trip_preserves_fields() -> None:
    """Wire ↔ kaos-agents value type must be lossless."""
    wire = SessionPolicyWire.for_persona("drafting")
    policy = wire.to_session_policy()
    wire_again = SessionPolicyWire.from_session_policy(policy)

    assert set(wire_again.allowed_groups) == set(wire.allowed_groups)
    assert set(wire_again.soft_ceiling) == set(wire.soft_ceiling)
    assert set(wire_again.denied_tools) == set(wire.denied_tools)
    assert wire_again.auto_narrow == wire.auto_narrow
    assert wire_again.auto_elevate == wire.auto_elevate
    assert wire_again.auto_loop == wire.auto_loop
    assert wire_again.max_loop_iterations == wire.max_loop_iterations
    assert wire_again.max_loop_cost_usd == wire.max_loop_cost_usd
    assert wire_again.max_loop_wall_clock_seconds == wire.max_loop_wall_clock_seconds


def test_to_session_policy_returns_kaos_agents_value_type() -> None:
    """``to_session_policy`` returns the canonical
    :class:`kaos_agents.types.session_policy.SessionPolicy` so the
    AgenticLoop can consume it directly."""
    from kaos_agents.types.session_policy import SessionPolicy

    wire = SessionPolicyWire()
    policy = wire.to_session_policy()
    assert isinstance(policy, SessionPolicy)
    # The kaos-agents type stores groups as frozensets — no leakage of
    # the list-based wire shape.
    assert isinstance(policy.allowed_groups, frozenset)
    assert isinstance(policy.soft_ceiling, frozenset)


def test_loop_budget_constraints_rejected() -> None:
    """Pydantic validation rejects illegal loop-budget values."""
    with pytest.raises(ValidationError):
        SessionPolicyWire(max_loop_iterations=0)
    with pytest.raises(ValidationError):
        SessionPolicyWire(max_loop_iterations=20)
    with pytest.raises(ValidationError):
        SessionPolicyWire(max_loop_cost_usd=0.0)
    with pytest.raises(ValidationError):
        SessionPolicyWire(max_loop_wall_clock_seconds=0.0)


def test_persona_field_is_typed_literal() -> None:
    """Persona is the three-way Literal — invalid values get rejected."""
    with pytest.raises(ValidationError):
        SessionPolicyWire(persona="invalid-persona")  # type: ignore[arg-type]
