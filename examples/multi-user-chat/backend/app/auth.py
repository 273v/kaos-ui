"""JWT-based auth dependency for multi-user-chat.

Replaces single-user-chat's shared-bearer-from-env model with a
per-user HS256 JWT carrying a ``sub`` (user_id / tenant_id) claim.
The tenant id from the token scopes every SessionStore call.

The shape is intentionally minimal — production deploys should swap
this for an OIDC code-flow handler that validates against the IdP's
JWKS. The substitution point is contained: pass an alternate
``decode_token`` to ``require_tenant`` and the rest of the pipeline
stays the same.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request


@dataclass(frozen=True, slots=True)
class TenantClaims:
    """The subset of JWT claims this app cares about."""

    tenant_id: str
    """Stable per-user identifier. Used as the namespace key in the VFS."""


def _jwt_secret() -> str:
    secret = os.environ.get("APP_JWT_SECRET", "")
    if not secret or len(secret) < 32:
        raise HTTPException(
            status_code=500,
            detail={
                "what": "APP_JWT_SECRET is missing or too short",
                "how_to_fix": "set APP_JWT_SECRET in .env to a 32+ char random value",
                "alternative": "head -c 32 /dev/urandom | base64",
            },
        )
    return secret


def decode_token(token: str, secret: str) -> TenantClaims:
    """Decode + validate a JWT and return its tenant claims.

    Raises 401 on every JWT-validation failure with an agent-friendly
    triple in the detail body. Replace this function in your subclass
    when migrating to OIDC — keep the return type and the rest of the
    pipeline is unchanged.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "what": f"invalid bearer token: {type(exc).__name__}",
                "how_to_fix": "obtain a fresh token from your IdP and retry",
            },
        ) from exc
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            status_code=401,
            detail={
                "what": "token missing 'sub' claim",
                "how_to_fix": "ensure your IdP populates sub with the user's stable id",
            },
        )
    # Defense in depth: sub is used as a VFS path component. Strip
    # anything that could traverse or pollute the path.
    if "/" in sub or "\\" in sub or ".." in sub:
        raise HTTPException(
            status_code=401,
            detail={
                "what": f"invalid 'sub' claim: {sub!r}",
                "how_to_fix": "use only [a-zA-Z0-9_-] in the sub claim",
            },
        )
    return TenantClaims(tenant_id=sub)


def require_tenant(request: Request) -> TenantClaims:
    """FastAPI dependency. 401s requests without a valid JWT.

    Returns the :class:`TenantClaims` carrying the authenticated
    tenant id. Every downstream handler that wants tenant-scoped
    data should ``tenant: TenantClaims = Depends(require_tenant)``
    and pass ``tenant.tenant_id`` into the SessionStore.
    """
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail={
                "what": "missing or malformed Authorization header",
                "how_to_fix": "send 'Authorization: Bearer <JWT>'",
            },
        )
    return decode_token(token, _jwt_secret())
