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
_CURATED: tuple[tuple[str, str, str], ...] = (
    # Default — fastest, cheapest current-gen Anthropic.
    ("anthropic:claude-haiku-4-5", "Claude Haiku 4.5", "Fast everyday chat"),
    ("anthropic:claude-sonnet-4-6", "Claude Sonnet 4.6", "Balanced reasoning"),
    ("anthropic:claude-opus-4-7", "Claude Opus 4.7", "Maximum reasoning"),
    # OpenAI flagship + cheap.
    ("openai:gpt-5", "GPT-5", "OpenAI flagship"),
    ("openai:gpt-5.5", "GPT-5.5", "Latest OpenAI"),
    ("openai:gpt-4.1-mini", "GPT-4.1 mini", "Cheap, capable"),
    # Google long-context.
    ("google:gemini-2.5-flash", "Gemini 2.5 Flash", "Long context, fast"),
    ("google:gemini-2.5-pro", "Gemini 2.5 Pro", "Long context, deep"),
    # xAI.
    ("xai:grok-3", "Grok 3", "Real-time leaning"),
    ("xai:grok-3-mini", "Grok 3 mini", "Cheap Grok"),
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
# Defense-in-depth for HIGH #3: the UI label says "Enable read-only
# tools", and this list keeps that promise even as the toolset grows.
# Audit before adding a glob: confirm every tool matched by the glob
# is genuinely side-effect-free (read / extract / search / classify).
READ_ONLY_TOOL_GLOBS: tuple[str, ...] = (
    # kaos-core: VFS + tool registry inspection — reads only.
    "kaos-core-vfs-list",
    "kaos-core-vfs-read",
    "kaos-core-list-tools",
    "kaos-core-list-resources",
    "kaos-core-tool-schema",
    # kaos-pdf: text/page/render reads + classify. ParsePDF + RenderPage
    # are read-only against the input file.
    "kaos-pdf-parse",
    "kaos-pdf-page-text",
    "kaos-pdf-render-page",
    "kaos-pdf-metadata",
    "kaos-pdf-search",
    "kaos-pdf-outline",
    "kaos-pdf-classify",
    # kaos-office: every entry is a read/parse path. Writers are out.
    "kaos-office-read*",
    "kaos-office-extract*",
    "kaos-office-search*",
    "kaos-office-list*",
    # kaos-content: corpus + entity + summary queries, all read-only.
    "kaos-content-search-document",
    "kaos-content-chunk-document",
    "kaos-content-summarize-document",
    "kaos-content-extract*",
    "kaos-content-filter*",
    "kaos-content-corpus-*",
    "kaos-content-sentences-*",
)


# Import-time validation. If the registry has drifted, the backend
# refuses to start — better than serving a 200 with a broken picker.
_validate_catalog()
