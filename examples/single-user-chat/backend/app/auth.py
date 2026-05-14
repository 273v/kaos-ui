"""Bearer-token auth dependency for the example extension routers.

Mirrors `kaos_agents.api.server._require_auth` (which is name-private
upstream) so our `/v1/chat/*` and `/v1/models` routes enforce the same
auth gate as the kaos-agents-native routes mounted on the same app.

Critical fix (CRITICAL #1 from review): without this, anyone could
list/patch/archive sessions and create upstream sessions because
`_bearer_from_request` in stream_proxy fell back to the env token.
That fallback is now ONLY used for the in-process proxy forward —
we still re-authenticate every inbound request via this dep.
"""

from __future__ import annotations

from fastapi import HTTPException, Request


def require_auth(request: Request) -> str | None:
    """FastAPI dependency. 401s requests without a valid bearer.

    Reads the same `app.state.api_settings` that kaos-agents'
    `create_app()` already populated, so our auth check stays
    consistent with the upstream contract:

    - Token configured → require `Authorization: Bearer <token>`,
      constant-time compared. Returns the derived tenant id.
    - `api_allow_unauth_localhost` mode → permit only 127.0.0.1 / ::1.
      Returns None (no tenant scoping).
    - Otherwise → 401 (defensive; create_app should have refused to
      start in this state).
    """
    settings = getattr(request.app.state, "api_settings", None)
    if settings is None:  # pragma: no cover — defensive
        raise HTTPException(
            status_code=500,
            detail=(
                "kaos-agents api_settings missing from app.state — did create_agent_app() run?"
            ),
        )

    if settings.api_token is not None:
        auth_header = request.headers.get("authorization", "")
        scheme, _, presented = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not settings.check_token(presented):
            raise HTTPException(
                status_code=401,
                detail=(
                    "Authentication required. Send 'Authorization: Bearer "
                    "<KAOS_AGENTS_API_API_TOKEN>' header (note the double "
                    "API_ prefix — see docs/PATTERNS.md P-001)."
                ),
            )
        return settings.tenant_id()

    if getattr(settings, "api_allow_unauth_localhost", False):
        # Match kaos-agents' localhost-only gate. We don't need to
        # re-emit the warning — kaos-agents' own dep does it on its
        # routes; ours just trusts the same gate.
        peer = request.client.host if request.client else ""
        if peer not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(
                status_code=401,
                detail=("Localhost-dev mode: only 127.0.0.1 / ::1 origins permitted."),
            )
        return None

    raise HTTPException(
        status_code=401,
        detail=(
            "Server-side misconfiguration: neither KAOS_AGENTS_API_API_TOKEN "
            "nor KAOS_AGENTS_API_API_ALLOW_UNAUTH_LOCALHOST is set."
        ),
    )
