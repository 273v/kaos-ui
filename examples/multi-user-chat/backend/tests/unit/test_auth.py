"""multi-user-chat — JWT auth dependency unit tests.

Pins the contract the SPA + every router relies on:
  - HS256 JWT decodes to TenantClaims when the sub claim is clean
  - Path-traversal / disallowed chars in sub are rejected
  - Missing sub, wrong signature, malformed header all 401
"""

from __future__ import annotations

import os

import jwt as jwt_lib
import pytest
from fastapi import HTTPException

os.environ.setdefault("APP_JWT_SECRET", "test-secret-that-is-32-chars-long-or-more-please-thanks")

from app.auth import (
    TenantClaims,
    _jwt_secret,
    decode_token,
)


def _token(payload: dict, secret: str | None = None) -> str:
    return jwt_lib.encode(payload, secret or _jwt_secret(), algorithm="HS256")


# ── happy path ───────────────────────────────────────────────────────


def test_valid_token_returns_tenant_claims() -> None:
    claims = decode_token(_token({"sub": "alice"}), _jwt_secret())
    assert isinstance(claims, TenantClaims)
    assert claims.tenant_id == "alice"


def test_complex_but_safe_sub_passes() -> None:
    """Hyphens / underscores / digits are fine in tenant ids."""
    claims = decode_token(_token({"sub": "user-42_test"}), _jwt_secret())
    assert claims.tenant_id == "user-42_test"


# ── rejected shapes ──────────────────────────────────────────────────


def test_wrong_signature_401s() -> None:
    bad_token = _token({"sub": "alice"}, secret="another-secret-with-32-or-more-thanks")
    with pytest.raises(HTTPException) as exc:
        decode_token(bad_token, _jwt_secret())
    assert exc.value.status_code == 401


def test_missing_sub_claim_401s() -> None:
    token = _token({"iss": "https://idp", "exp": 9_999_999_999})
    with pytest.raises(HTTPException) as exc:
        decode_token(token, _jwt_secret())
    assert exc.value.status_code == 401


def test_empty_sub_claim_401s() -> None:
    with pytest.raises(HTTPException) as exc:
        decode_token(_token({"sub": ""}), _jwt_secret())
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "evil_sub",
    [
        "../etc/passwd",
        "user/../other",
        "user\\..\\other",
        "user/../../system",
    ],
)
def test_path_traversal_in_sub_401s(evil_sub: str) -> None:
    """Path-traversal in the sub claim must NOT escape the tenant prefix."""
    with pytest.raises(HTTPException) as exc:
        decode_token(_token({"sub": evil_sub}), _jwt_secret())
    assert exc.value.status_code == 401


def test_expired_token_401s() -> None:
    """PyJWT auto-validates exp; expired tokens 401."""
    with pytest.raises(HTTPException) as exc:
        decode_token(_token({"sub": "alice", "exp": 1}), _jwt_secret())
    assert exc.value.status_code == 401
