"""Liveness + readiness probe.

``GET /v1/health`` returns:

- ``status``: ``"ok"`` (≥1 provider configured) or ``"degraded"``
  (zero providers configured) — returns HTTP 503 on degraded.
- ``build_sha``: stable per-build SHA (12 hex chars). Sessions
  stamp this into their meta sidecar at create time so the SPA can
  badge sessions created on an older build.
- ``providers``: per-provider configured state (``configured`` |
  ``unconfigured``). Honest about which providers can actually be
  called by the upstream kaos-agents process.

#590 / B1.8 — pre-fix, this endpoint returned HTTP 200 with
``status=ok`` unconditionally even when zero providers were
configured. A load balancer + a docker-compose healthcheck both
read "OK" while every chat turn failed at the first LLM call. The
audit (production-reliability + observability O0.x) flagged this
as the "health lies" anti-pattern.

Configured-vs-unconfigured is the minimum-honest signal. Real
provider reachability (live ``/v1/models`` probe per provider,
cached 30s) is a v2 ask — it doubles the rate-limit surface on
every health check and the SPA backend doesn't own provider
quotas.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata as _md
import os

from fastapi import APIRouter, Response, status

router = APIRouter(tags=["health"])


# Provider env-var inventory. Tuple of ``(provider_name, env_vars)``
# where the provider is "configured" iff any of the listed env vars
# is set + non-empty. We check both the ``KAOS_LLM_*_API_KEY`` prefix
# (preferred — pydantic-settings env_prefix) and the legacy
# ``<PROVIDER>_API_KEY`` shapes (per kaos-llm-client's legacy
# fallbacks in ``settings.py``).
_PROVIDER_ENV_VARS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("openai", ("KAOS_LLM_OPENAI_API_KEY", "OPENAI_API_KEY")),
    ("anthropic", ("KAOS_LLM_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")),
    (
        "google",
        (
            "KAOS_LLM_GOOGLE_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENERATIVE_AI_API_KEY",
        ),
    ),
    ("xai", ("KAOS_LLM_XAI_API_KEY", "XAI_API_KEY")),
    ("groq", ("KAOS_LLM_GROQ_API_KEY", "GROQ_API_KEY")),
    ("mistral", ("KAOS_LLM_MISTRAL_API_KEY", "MISTRAL_API_KEY")),
    (
        "openrouter",
        (
            "KAOS_LLM_OPENROUTER_API_KEY",
            "OPENROUTER_API_KEY",
        ),
    ),
)


def _provider_status() -> dict[str, str]:
    """Return ``{provider_name: "configured" | "unconfigured"}`` for
    every provider in the inventory.

    Sync + cheap — no network calls. Re-evaluates per request so a
    runtime env-var change (e.g. operator rotates an API key) is
    visible immediately.
    """
    out: dict[str, str] = {}
    for name, env_vars in _PROVIDER_ENV_VARS:
        configured = any(os.environ.get(v) for v in env_vars)
        out[name] = "configured" if configured else "unconfigured"
    return out


@functools.lru_cache(maxsize=1)
def current_build_sha() -> str:
    """Short identifier for the running build.

    Computed once at first call from the installed versions of every
    kaos-* package + the SPA's own version. Cached for process lifetime
    so every endpoint hands out the same value, and so sessions stamp
    a stable identifier into their meta.

    Format: 12-char hex of sha256 over a sorted (pkg, version) list.
    Stable across restarts of the same build; changes the moment any
    kaos-* wheel is upgraded — which is exactly the "this session
    predates a known fix" signal the sidebar needs.
    """
    components: list[tuple[str, str]] = []
    candidates = (
        "single-user-chat-backend",
        "kaos-core",
        "kaos-agents",
        "kaos-content",
        "kaos-pdf",
        "kaos-office",
        "kaos-llm-core",
        "kaos-llm-client",
        "kaos-ui",
    )
    for name in candidates:
        try:
            components.append((name, _md.version(name)))
        except _md.PackageNotFoundError:
            continue
    payload = "\n".join(f"{n}=={v}" for n, v in sorted(components)).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


@router.get("/health")
async def health(response: Response) -> dict[str, object]:
    """Honest liveness + readiness — see module docstring."""
    providers = _provider_status()
    any_configured = any(v == "configured" for v in providers.values())
    if not any_configured:
        # Zero providers configured = every chat turn will fail. Tell
        # load balancers + healthchecks the truth.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "degraded",
            "reason": "no_provider_api_keys_configured",
            "providers": providers,
            "build_sha": current_build_sha(),
        }
    return {
        "status": "ok",
        "providers": providers,
        "build_sha": current_build_sha(),
    }
