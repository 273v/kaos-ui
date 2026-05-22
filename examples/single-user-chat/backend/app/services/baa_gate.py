"""BAA / HIPAA enforcement gate for the SPA chat router.

Plan §Issue 4 ("No per-vendor PII egress log") requires that when a
session is flagged ``hipaa_required=True``, attempts to use a
provider without a Business Associate Agreement are refused at the
edge with HTTP 403.

This module owns the gate. When kaos-llm-client PR #27
(``feat/issue-4-vendor-egress-audit``) lands on PyPI as 0.1.3+, the
``_BAA_ELIGIBLE_PROVIDERS`` set + the helper below can be deleted in
favour of ``kaos_llm_client.profiles.assert_baa_compliance``.  Until
then the SPA backend ships a vendored gate so the launch-blocker
acceptance criterion lands without waiting on a PyPI release.

The gate is conservative: provider eligibility defaults to False
everywhere, and operators opt a provider in via the explicit set
below. Defaulting to True would silently allow PHI through providers
that aren't actually BAA-eligible on a given tenant contract.

Configuration source:
``kaos-modules/docs/compliance/sub-processors.md`` is the canonical
"who has a signed BAA" inventory. The set below mirrors the BAA-
available column of that document. When a vendor's status changes,
update this set AND the sub-processors.md table in the same PR.
"""

from __future__ import annotations

from dataclasses import dataclass

# Vendors flagged as BAA-eligible in the 2026-05 audit inventory.
# See ``kaos-modules/docs/compliance/sub-processors.md``.
#
# Conservative default — vendors not in this set are treated as
# NOT BAA-eligible and a hipaa_required session targeting them is
# refused at the gate.
_BAA_ELIGIBLE_PROVIDERS: frozenset[str] = frozenset(
    {
        # Enterprise BAA available on signed contract.
        # Operators MUST verify the contract is in place on their
        # tenant before flipping any production session to
        # hipaa_required=True against these providers.
        "azure-openai",
        "aws-bedrock",
        # The next three carry BAA-eligible enterprise tiers; the
        # default platform/free tier does NOT include a BAA. The
        # gate only checks the provider identifier, not the tier —
        # operators are responsible for pinning the right base_url
        # / org / project to the BAA-enrolled side of the provider.
        "anthropic",
        "openai",
        "google",
    }
)


@dataclass(frozen=True, slots=True)
class TenantPolicyViolation:
    """Typed payload for a 403 response when the BAA gate trips.

    Includes the provider name, the model, the constraint that fired,
    and a remediation hint the UI can show as a "BAA required" banner.
    """

    provider: str
    model: str
    constraint: str
    detail: str


def _infer_provider(model: str) -> str:
    """Infer the provider prefix from a model identifier.

    Accepts ``provider:model`` (canonical SPA shape) and a few
    historical bare-model shapes (``claude-…``, ``gpt-…``, ``gemini-…``,
    ``grok-…``). Returns the lowercase provider name.
    """
    if ":" in model:
        return model.split(":", 1)[0].strip().lower()
    bare = model.strip().lower()
    if bare.startswith("claude"):
        return "anthropic"
    if bare.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if bare.startswith("gemini"):
        return "google"
    if bare.startswith("grok"):
        return "xai"
    return "unknown"


def assert_session_baa_compliance(
    *,
    model: str,
    hipaa_required: bool,
    allowed_providers: list[str] | tuple[str, ...] | None = None,
) -> None:
    """Refuse the call when a HIPAA-protected session targets a
    provider without a Business Associate Agreement.

    Two constraints are checked, in order:

    1. ``allowed_providers`` (per-tenant allowlist). If non-empty and
       the resolved provider isn't on the list, refuse — even when
       ``hipaa_required=False``. This is the explicit-allowlist case
       (e.g. "this tenant only uses Azure-OpenAI").
    2. ``hipaa_required``. When True, the resolved provider must be
       in ``_BAA_ELIGIBLE_PROVIDERS``; otherwise refuse.

    Raises ``TenantPolicyError`` on either failure. The error payload
    carries provider/model/constraint/detail so the caller (router)
    can map it to a typed 403 response without re-deriving anything.
    """
    provider = _infer_provider(model)

    if allowed_providers:
        # Normalise the allowlist for comparison. Operators can
        # provide either canonical ``provider`` names or ``provider:``-
        # prefixed model IDs by accident; we accept both shapes.
        allowed = {p.split(":", 1)[0].strip().lower() for p in allowed_providers if p}
        if provider not in allowed:
            raise TenantPolicyError(
                violation=TenantPolicyViolation(
                    provider=provider,
                    model=model,
                    constraint="allowed_providers",
                    detail=(
                        f"Provider {provider!r} is not in the tenant's allowed-provider "
                        f"list {sorted(allowed)!r}. "
                        f"Fix: pick a model whose provider is on the list, or update "
                        f"the session's allowed_providers via PATCH /v1/chat/sessions/"
                        f"{{session_id}}/meta. "
                        f"Alternative: clear allowed_providers to disable the allowlist."
                    ),
                )
            )

    if hipaa_required and provider not in _BAA_ELIGIBLE_PROVIDERS:
        raise TenantPolicyError(
            violation=TenantPolicyViolation(
                provider=provider,
                model=model,
                constraint="hipaa_required",
                detail=(
                    f"Provider {provider!r} is not BAA-eligible but the session "
                    f"requires HIPAA compliance. Fix: route this session to a "
                    f"BAA-covered provider (Azure OpenAI, AWS Bedrock, or a signed "
                    f"enterprise contract with Anthropic / OpenAI / Google). "
                    f"Alternative: lift hipaa_required for non-PHI workloads via "
                    f"PATCH /v1/chat/sessions/{{session_id}}/meta."
                ),
            )
        )


class TenantPolicyError(Exception):
    """Raised by ``assert_session_baa_compliance`` when the policy gate trips."""

    def __init__(self, *, violation: TenantPolicyViolation) -> None:
        super().__init__(violation.detail)
        self.violation = violation


__all__ = [
    "TenantPolicyError",
    "TenantPolicyViolation",
    "assert_session_baa_compliance",
]
