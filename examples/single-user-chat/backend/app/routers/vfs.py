"""/v1/chat/sessions/{session_id}/vfs — session VFS explorer endpoint.

Stage 1 of the 2026-05-26 VFS explorer plan
(``kaos-modules/docs/plans/2026-05-26-spa-vfs-explorer-design.md``).

Peer of ``/files``; lists everything in the session VFS subtree
(``sessions/{scoped}/**``) so the SPA's VFS panel can show the full
agent-visible state — uploads, agent-written artifacts, and (opt-in)
the SPA's own parse / metadata sidecars.

Read-only. Write affordances (force re-parse, delete artifact) are
deferred to v2; the explorer ships as a developer / operator surface
that makes session state inspectable without grep'ing structured logs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kaos_core import KaosRuntime

from app.auth import require_auth
from app.deps import get_runtime, get_session_store
from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import VfsListResponse
from app.persistence.sessions import SessionStore
from app.services.vfs import VfsPrefixError, walk_session_vfs

router = APIRouter(tags=["vfs"])
logger = app_logger("vfs_router")

StoreDep = Annotated[SessionStore, Depends(get_session_store)]
RuntimeDep = Annotated[KaosRuntime, Depends(get_runtime)]
TenantDep = Annotated[str | None, Depends(require_auth)]


@router.get(
    "/sessions/{session_id}/vfs",
    response_model=VfsListResponse,
)
async def list_session_vfs(
    session_id: str,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
    prefix: Annotated[
        str,
        Query(
            description=(
                "Sub-prefix under ``sessions/{scoped}/`` to walk. Empty "
                "string walks the whole session subtree. Cannot contain "
                "``..`` segments — relative escapes return 400."
            ),
        ),
    ] = "",
    recursive: Annotated[
        bool,
        Query(
            description=(
                "When false, walk only immediate children (depth=1). "
                "Ignored if ``max_depth`` is set."
            ),
        ),
    ] = True,
    max_depth: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Hard cap on walk depth (mirrors VFSWalkOptions.max_depth). "
                "Overrides ``recursive``."
            ),
        ),
    ] = None,
    pattern: Annotated[
        str | None,
        Query(
            description=(
                "Optional glob pattern filter applied to leaf paths "
                "(mirrors VFSWalkOptions.patterns)."
            ),
        ),
    ] = None,
    include_sidecars: Annotated[
        bool,
        Query(
            description=(
                "When true, include the sibling ``sidecars/{scoped}/`` "
                "subtree and any in-tree ``.kaos.json`` / ``.meta.json`` "
                "paths in the result. Default-off so end-user views don't "
                "show internal parse intermediates."
            ),
        ),
    ] = False,
    cursor: Annotated[
        str | None,
        Query(description="Opaque pagination cursor returned by a prior call."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Max entries per page (hard-capped at 1000)."),
    ] = 200,
) -> VfsListResponse:
    """Walk the session VFS subtree and return a paginated tree.

    Always validates the session exists (404 on miss) before walking
    the VFS — otherwise the walk would return an empty tree for any
    string and leak existence-of-session timing.
    """
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Resolve recursive → max_depth (max_depth wins when explicit).
    effective_depth: int | None
    if max_depth is not None:
        effective_depth = max_depth
    elif recursive:
        effective_depth = None
    else:
        effective_depth = 1

    try:
        return await walk_session_vfs(
            runtime,
            session_id=session_id,
            tenant_id=tenant_id,
            prefix=prefix,
            max_depth=effective_depth,
            pattern=pattern,
            include_sidecars=include_sidecars,
            cursor=cursor,
            limit=limit,
        )
    except VfsPrefixError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "what": "prefix is not a safe relative path inside the session VFS subtree",
                "how_to_fix": (
                    "pass a relative path like ``files/`` or ``artifacts/``; "
                    "absolute paths and ``..`` segments are rejected"
                ),
                "received": prefix,
                "error": str(exc),
            },
        ) from exc
    except Exception as exc:
        logger.exception(
            "vfs.walk failed for session=%s prefix=%r: %s",
            session_id,
            prefix,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "what": "VFS walk raised an unexpected error",
                "how_to_fix": "retry; if persistent, report with the session id",
            },
        ) from exc
