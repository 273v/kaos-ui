"""Model picker catalog, validated against the live `MODEL_PRICING`
registry from `kaos-llm-client`.

The curated tuple below is the human-readable selection shown in the
SPA's model picker. On module import we cross-check every id against
`kaos_llm_client.cost.MODEL_PRICING`; mismatches raise immediately.
This is the **registry guard** — it fails CI loudly when a model id
rots out from under us. See docs/PRD.md § 6 (Constraints / Models).
"""

from __future__ import annotations

from kaos_llm_client.cost import MODEL_PRICING, PRICING_LAST_UPDATED

from app.models import ModelEntry

# (id, label, recommended_for). `id` is the `provider:model` string we
# pass to kaos-agents. `model` part must appear in MODEL_PRICING.
#
# Audience: attorneys billing $hundreds to $thousands/hour. Cheap / older
# tiers are deliberately EXCLUDED — the cost of a wrong answer dwarfs
# the inference-cost delta between frontier and "mini" tiers. Floor:
# gpt ≥ 5.4, claude ≥ 4.5, gemini ≥ 2.5. xAI / Grok intentionally
# omitted (not certified for legal-research use here).
_CURATED: tuple[tuple[str, str, str], ...] = (
    # Anthropic — frontier first; ordering puts the default on top.
    ("anthropic:claude-opus-4-7", "Claude Opus 4.7", "Maximum reasoning — default for legal work"),
    ("anthropic:claude-sonnet-4-6", "Claude Sonnet 4.6", "Balanced reasoning"),
    ("anthropic:claude-haiku-4-5", "Claude Haiku 4.5", "Fast classification / routing"),
    # OpenAI flagship.
    ("openai:gpt-5.5", "GPT-5.5", "OpenAI flagship — alternate default"),
    ("openai:gpt-5.4", "GPT-5.4", "OpenAI frontier"),
    ("openai:gpt-5.4-mini", "GPT-5.4 mini", "Fast OpenAI"),
    # Google long-context.
    ("google:gemini-2.5-pro", "Gemini 2.5 Pro", "Long context, deep reasoning"),
    ("google:gemini-2.5-flash", "Gemini 2.5 Flash", "Long context, fast"),
)


def _strip_provider(model_id: str) -> str:
    """`'anthropic:claude-haiku-4-5'` → `'claude-haiku-4-5'`."""
    _, _, model = model_id.partition(":")
    return model


def _validate_catalog() -> None:
    """Fail loudly if any curated id is missing from MODEL_PRICING."""
    registry = set(MODEL_PRICING.keys())
    missing = [
        model_id for (model_id, _, _) in _CURATED if _strip_provider(model_id) not in registry
    ]
    if missing:
        raise RuntimeError(
            "catalog rot: the following model ids are no longer in "
            f"kaos_llm_client.cost.MODEL_PRICING (last updated "
            f"{PRICING_LAST_UPDATED}): {missing!r}. "
            "Fix in backend/app/services/catalog.py."
        )


_PROVIDER_BY_ID = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "xai": "xai",
}


def build_catalog() -> list[ModelEntry]:
    """Return the curated catalog as `ModelEntry` records.

    Validates against `MODEL_PRICING` on every call. The cost is
    negligible (set lookup over ~18 keys) and it converts the
    registry-guard test into a request-time safeguard.
    """
    _validate_catalog()
    out: list[ModelEntry] = []
    for model_id, label, hint in _CURATED:
        provider_part = model_id.split(":", 1)[0]
        if provider_part not in _PROVIDER_BY_ID:
            raise RuntimeError(
                f"catalog: unknown provider prefix {provider_part!r} in {model_id!r}. "
                f"Known providers: {list(_PROVIDER_BY_ID)}."
            )
        out.append(
            ModelEntry(
                id=model_id,
                label=label,
                provider=provider_part,  # ty: ignore[invalid-argument-type]
                recommended_for=hint,
            )
        )
    return out


# ── Read-only KAOS tool allowlist ────────────────────────────────────
#
# When a session has `tools_enabled=True`, the proxy sends THIS glob
# list as `MessageRequest.tools`. Anything outside the allowlist will
# never be bridged into the agent's ReAct loop, even if a future kaos-
# module adds write tools to the runtime.
#
# Defense-in-depth: the UI label says "Enable read-only tools", and
# this list keeps that promise even as the toolset grows. Before adding
# a glob, confirm every tool matched is genuinely side-effect-free
# (read / extract / search / classify).
READ_ONLY_TOOL_GLOBS: tuple[str, ...] = (
    # kaos-core: VFS reads + tool / artifact / config introspection.
    # credentials-check is excluded — it exposes which auth secrets are
    # configured, which we don't surface to the agent by default.
    "kaos-core-vfs-list",
    "kaos-core-vfs-read",
    "kaos-core-vfs-stat",
    "kaos-core-list-tools",
    "kaos-core-list-resources",
    "kaos-core-tool-schema",
    "kaos-core-artifacts-inspect",
    "kaos-core-artifacts-list",
    "kaos-core-config-show",
    # kaos-pdf: every tool is read-only (extract / search / render /
    # metadata / classify / outline). The 0.1.0a2 names are unhyphenated
    # under each capability — `kaos-pdf-extract-parse`, etc.
    "kaos-pdf-*",
    # kaos-office: read / parse / metadata / search / list. The
    # write-docx / write-pptx / write-xlsx tools are deliberately
    # excluded — they would mutate the user's session storage.
    "kaos-office-get-*",
    "kaos-office-list-*",
    "kaos-office-parse-*",
    "kaos-office-metadata",
    "kaos-office-xlsx-metadata",
    "kaos-office-search",
    "kaos-office-search-pptx",
    # kaos-content: all tools are read-only over the parsed document
    # AST — search / chunk / extract / corpus / sentences / serialize /
    # stats / parse-markdown / dedup-semantic.
    "kaos-content-*",
    # kaos-citations: typed Bluebook / financial / accounting citation
    # extraction. extract + validate + doctor are all readOnlyHint=True.
    "kaos-citations-*",
    # kaos-source: 30 connectors — Federal Register / eCFR / EDGAR /
    # GovInfo / GLEIF REST APIs, plus generic HTTP / archive / file
    # metadata / forensic parsers (vcard / eml / mbox / pacer / exif).
    # All read-oriented; materialize writes to the runtime VFS only.
    "kaos-source-*",
)


# Import-time validation. If the registry has drifted, the backend
# refuses to start — better than serving a 200 with a broken picker.
_validate_catalog()
