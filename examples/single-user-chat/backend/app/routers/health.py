"""Liveness probe. Kaos-agents' bundled API doesn't ship a /health
endpoint; this is our addition for docker-compose's healthcheck.

Also exposes the running build identity so the SPA can mark
sessions created on an older build as ``stale`` — see P3-10 in
``kaos-modules/docs/plans/2026-05-18-cross-layer-issue-inventory.md``
for the sidebar UX. Build SHA is computed at process start from
the importable ``app`` package + the kaos-* wheels currently
resolved, hashed to a short marker. Sessions stamp this SHA into
their meta sidecar at create time; the SPA compares meta.build_sha
to /v1/health.build_sha to decide whether to badge a session as
predating the current build.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata as _md

from fastapi import APIRouter

router = APIRouter(tags=["health"])


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
async def health() -> dict[str, str]:
    return {"status": "ok", "build_sha": current_build_sha()}
