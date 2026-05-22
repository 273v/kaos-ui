"""Unit tests for the BAA / HIPAA enforcement gate (plan §Issue 4).

Closes the SPA-side half of the launch-blocker. When kaos-llm-client
0.1.3+ ships ``profiles.assert_baa_compliance`` on PyPI, the local
helper can be deleted; until then, this test pack pins the contract.
"""

from __future__ import annotations

import pytest

from app.services.baa_gate import (
    TenantPolicyError,
    TenantPolicyViolation,
    _infer_provider,
    assert_session_baa_compliance,
)

# ── _infer_provider ──────────────────────────────────────────────────


@pytest.mark.unit
def test_infer_provider_recognises_provider_prefixed_models() -> None:
    """Canonical SPA shape: ``provider:model``."""
    assert _infer_provider("anthropic:claude-sonnet-4-6") == "anthropic"
    assert _infer_provider("openai:gpt-5.4-mini") == "openai"
    assert _infer_provider("google:gemini-2.5-flash") == "google"
    assert _infer_provider("xai:grok-4") == "xai"


@pytest.mark.unit
def test_infer_provider_recognises_bare_model_families() -> None:
    """Historical bare-model shapes (no ``provider:`` prefix)."""
    assert _infer_provider("claude-opus-4-7") == "anthropic"
    assert _infer_provider("gpt-5.4-mini") == "openai"
    assert _infer_provider("o3") == "openai"
    assert _infer_provider("gemini-2.5-flash") == "google"
    assert _infer_provider("grok-4") == "xai"


@pytest.mark.unit
def test_infer_provider_returns_unknown_for_unrecognised_model() -> None:
    """The gate must not silently succeed on an unrecognised model —
    ``unknown`` falls through to the BAA check and is treated as
    NOT BAA-eligible."""
    assert _infer_provider("totally-made-up-model") == "unknown"
    assert _infer_provider("mistral-large") == "unknown"


# ── HIPAA gate ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_hipaa_gate_passes_for_non_phi_session() -> None:
    """``hipaa_required=False`` bypasses the BAA constraint entirely."""
    assert_session_baa_compliance(
        model="xai:grok-4",  # xAI not in BAA set
        hipaa_required=False,
    )


@pytest.mark.unit
def test_hipaa_gate_passes_for_baa_eligible_provider() -> None:
    """Anthropic / OpenAI / Google / Azure / Bedrock are in the
    enterprise-BAA set. Operators are responsible for verifying the
    contract is actually in place on their tenant."""
    for model in (
        "anthropic:claude-sonnet-4-6",
        "openai:gpt-5.4-mini",
        "google:gemini-2.5-flash",
        "azure-openai:gpt-5.4",
        "aws-bedrock:claude-sonnet-4-6",
    ):
        assert_session_baa_compliance(model=model, hipaa_required=True)


@pytest.mark.unit
def test_hipaa_gate_raises_for_non_baa_provider() -> None:
    """xAI is explicitly NOT in the BAA set — the gate refuses."""
    with pytest.raises(TenantPolicyError) as exc_info:
        assert_session_baa_compliance(
            model="xai:grok-4",
            hipaa_required=True,
        )
    v = exc_info.value.violation
    assert v.provider == "xai"
    assert v.model == "xai:grok-4"
    assert v.constraint == "hipaa_required"
    assert "BAA" in v.detail
    assert "Fix" in v.detail


@pytest.mark.unit
def test_hipaa_gate_raises_for_unknown_provider() -> None:
    """An unrecognised model can't be proven BAA-eligible — fail closed."""
    with pytest.raises(TenantPolicyError) as exc_info:
        assert_session_baa_compliance(
            model="some-new-provider:exotic-model",
            hipaa_required=True,
        )
    assert exc_info.value.violation.constraint == "hipaa_required"


# ── allowed_providers gate ───────────────────────────────────────────


@pytest.mark.unit
def test_allowed_providers_empty_is_treated_as_no_allowlist() -> None:
    """Empty list / None ⇒ no allowlist constraint. Pre-existing
    sessions without an allowlist must continue to work."""
    assert_session_baa_compliance(
        model="anthropic:claude-sonnet-4-6",
        hipaa_required=False,
        allowed_providers=None,
    )
    assert_session_baa_compliance(
        model="anthropic:claude-sonnet-4-6",
        hipaa_required=False,
        allowed_providers=[],
    )


@pytest.mark.unit
def test_allowed_providers_passes_for_listed_provider() -> None:
    """A model whose provider is on the allowlist passes the gate."""
    assert_session_baa_compliance(
        model="anthropic:claude-sonnet-4-6",
        hipaa_required=False,
        allowed_providers=["anthropic"],
    )


@pytest.mark.unit
def test_allowed_providers_rejects_off_list_provider() -> None:
    """An off-list provider is refused EVEN WHEN hipaa_required=False —
    the allowlist is independent of the BAA constraint."""
    with pytest.raises(TenantPolicyError) as exc_info:
        assert_session_baa_compliance(
            model="openai:gpt-5.4-mini",
            hipaa_required=False,
            allowed_providers=["anthropic"],
        )
    v = exc_info.value.violation
    assert v.constraint == "allowed_providers"
    assert v.provider == "openai"
    assert "anthropic" in v.detail


@pytest.mark.unit
def test_allowed_providers_accepts_provider_prefixed_entries() -> None:
    """Operators sometimes paste ``provider:model`` IDs into the
    allowlist by accident; the gate normalises to provider before
    comparing."""
    assert_session_baa_compliance(
        model="anthropic:claude-sonnet-4-6",
        hipaa_required=False,
        allowed_providers=["anthropic:claude-sonnet-4-6"],
    )


@pytest.mark.unit
def test_allowlist_runs_before_hipaa_gate() -> None:
    """When BOTH constraints would trip, the allowlist takes
    precedence — its message is more actionable than the BAA one
    (operator intentionally narrowed the surface)."""
    with pytest.raises(TenantPolicyError) as exc_info:
        assert_session_baa_compliance(
            model="xai:grok-4",
            hipaa_required=True,
            allowed_providers=["anthropic"],
        )
    assert exc_info.value.violation.constraint == "allowed_providers"


# ── TenantPolicyViolation payload ────────────────────────────────────


@pytest.mark.unit
def test_violation_payload_carries_required_fields() -> None:
    """The 403 response payload exposes the four fields the router
    serialises into the JSON body. Pinning the field set prevents a
    future refactor from silently dropping ``constraint`` (the
    discriminator the SPA UI switches on)."""
    v = TenantPolicyViolation(
        provider="xai",
        model="xai:grok-4",
        constraint="hipaa_required",
        detail="example",
    )
    assert v.provider == "xai"
    assert v.model == "xai:grok-4"
    assert v.constraint == "hipaa_required"
    assert v.detail == "example"
