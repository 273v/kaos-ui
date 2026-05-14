"""Liveness probe. Kaos-agents' bundled API doesn't ship a /health
endpoint; this is our addition for docker-compose's healthcheck."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
