"""Session VFS walker — backs ``GET /v1/chat/sessions/{id}/vfs``.

Wraps ``runtime.vfs.walk(prefix, context_id, options)`` with three
SPA-specific concerns:

1. **Session scoping + path safety.** The caller can pass a relative
   ``prefix`` (e.g. ``"files/"``, ``"artifacts/"``) but never an
   absolute path or one that escapes the session subtree with ``..``.
   We compose the walk root from
   ``f"sessions/{scoped}/{prefix}"`` after a strict sanitization
   pass; anything resolving outside the session subtree returns 400.
2. **Sidecar exclusion.** The SPA's parse pipeline writes
   ``.kaos.json`` and ``.meta.json`` sidecars under a sibling
   ``sidecars/{scoped}/`` namespace (per #583). Operators want to see
   them sometimes; lawyers should never. Default-off; opt-in via
   ``include_sidecars``.
3. **Per-node enrichment.** When a walked path looks like a user
   upload (``sessions/{scoped}/files/<name>``) we join its
   ``.meta.json`` sidecar (cheap lookup via
   :func:`app.services.uploads._sidecar_path`) so the panel can show
   parse status + the AST summary excerpt without a second round-trip.

Returns a tree-shaped :class:`VfsListResponse` (the route's response
model) plus a ``next_cursor`` for pagination — the underlying
``runtime.vfs.walk`` is one shot, so pagination is post-hoc list
slicing in this service.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from app.logging_setup import app_logger
from app.models import VfsListResponse, VfsNode
from app.services.uploads import (
    _legacy_sidecar_path,
    _scoped_session_prefix,
    _sidecar_path,
    _sidecar_prefix,
)

if TYPE_CHECKING:
    from kaos_core import KaosRuntime

logger = app_logger("vfs_service")

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000

_SIDECAR_SUFFIXES: tuple[str, ...] = (".kaos.json", ".meta.json")


class VfsPrefixError(ValueError):
    """Raised when the caller's ``prefix`` resolves outside the session subtree."""


def _normalize_prefix(prefix: str) -> str:
    """Validate + normalize a caller-supplied prefix.

    Strips leading slash, rejects ``..`` segments, collapses doubled
    slashes. Empty / None / ``"/"`` all normalize to ``""``.
    """
    if not prefix:
        return ""
    raw = prefix.lstrip("/")
    parts = [p for p in raw.split("/") if p]
    for part in parts:
        if part == ".." or part == "." or "\\" in part:
            raise VfsPrefixError(f"prefix segment {part!r} not allowed")
    normalized = "/".join(parts)
    # Walk-shape: a trailing slash is fine for "directory" prefixes but
    # we strip it consistently here and re-add downstream.
    return normalized.rstrip("/")


def _parse_timestamp(raw: str | None) -> datetime | None:
    """Best-effort ISO-8601 parse for VFSMetadata timestamps."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _is_sidecar_path(path: str) -> bool:
    """Return True iff ``path`` ends with a known sidecar suffix.

    Catches both the out-of-tree ``sidecars/{scoped}/<name>.kaos.json``
    location and the legacy in-tree
    ``sessions/{scoped}/files/<name>.kaos.json`` shape.
    """
    return any(path.endswith(suffix) for suffix in _SIDECAR_SUFFIXES)


def _relative_to_session(path: str, session_root: str) -> str:
    """Strip the ``sessions/{scoped}/`` prefix from ``path`` for UI display."""
    if path.startswith(session_root):
        rel = path[len(session_root) :]
        return rel.lstrip("/")
    return path


async def _try_load_meta_sidecar(
    runtime: KaosRuntime,
    *,
    session_id: str,
    tenant_id: str | None,
    filename: str,
) -> dict | None:
    """Read + parse the ``.meta.json`` sidecar for one uploaded file.

    Tries the out-of-tree sidecar first (#583), falls back to the
    legacy in-tree location. Returns ``None`` on any read / parse
    failure — sidecars are informational; their absence is not an
    error condition for the VFS walk.
    """
    for path in (
        _sidecar_path(session_id, filename, ".meta.json", tenant_id=tenant_id),
        _legacy_sidecar_path(session_id, filename, ".meta.json", tenant_id=tenant_id),
    ):
        try:
            raw = await runtime.vfs.read(path, context_id=session_id)
        except Exception:
            continue
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    return None


async def _enrich_upload_node(
    runtime: KaosRuntime,
    *,
    node: VfsNode,
    session_id: str,
    tenant_id: str | None,
) -> VfsNode:
    """Populate ``parse_status`` + ``summary_excerpt`` for an upload node.

    Cheap because the meta sidecar is a small JSON blob. Returns the
    node unchanged when the sidecar is missing / unparseable so the
    walk result is always a complete tree even if a sibling sidecar
    is in a weird state.
    """
    if not node.is_upload:
        return node
    # The relative path under the session root is "files/<filename>";
    # the meta-sidecar lookup needs the bare filename.
    rel = node.relative_path
    if not rel.startswith("files/"):
        return node
    filename = rel[len("files/") :]
    if "/" in filename:
        # Subdirectory under files/ — outside the SPA's flat-files
        # convention. Skip enrichment; the node still surfaces.
        return node

    meta = await _try_load_meta_sidecar(
        runtime, session_id=session_id, tenant_id=tenant_id, filename=filename
    )
    if not meta:
        return node

    parse = meta.get("parse") if isinstance(meta, dict) else None
    parse_status: str | None = None
    if isinstance(parse, dict):
        raw_status = parse.get("status")
        if raw_status in ("ready", "pending", "failed"):
            parse_status = raw_status

    summary = meta.get("summary") if isinstance(meta, dict) else None
    excerpt: str | None = None
    if isinstance(summary, str) and summary.strip():
        excerpt = summary.strip()[:160]

    return node.model_copy(
        update={
            "parse_status": parse_status,
            "summary_excerpt": excerpt,
        }
    )


def _entry_to_node(
    *,
    path: str,
    metadata,
    session_root: str,
    sidecar_root: str,
) -> VfsNode:
    """Convert a kaos-core VFSWalkEntry into the SPA's VfsNode shape."""
    rel = _relative_to_session(path, session_root)
    # Note: the kaos-core walker lives in the same VFS root the SPA
    # uses, so paths returned share the ``sessions/{scoped}/...`` prefix.
    is_sidecar = _is_sidecar_path(path) or path.startswith(sidecar_root)
    is_upload = rel.startswith("files/") and not is_sidecar
    is_artifact = rel.startswith("artifacts/")

    return VfsNode(
        path=path,
        relative_path=rel,
        kind="directory" if (metadata.kind == "directory") else "file",
        size_bytes=metadata.size if metadata.kind != "directory" else None,
        mime_type=metadata.mime_type,
        created_at=_parse_timestamp(metadata.created_at),
        modified_at=_parse_timestamp(metadata.modified_at),
        is_sidecar=is_sidecar,
        is_upload=is_upload,
        is_artifact=is_artifact,
        parse_status=None,
        summary_excerpt=None,
    )


async def walk_session_vfs(
    runtime: KaosRuntime,
    *,
    session_id: str,
    tenant_id: str | None,
    prefix: str = "",
    max_depth: int | None = None,
    pattern: str | None = None,
    include_sidecars: bool = False,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> VfsListResponse:
    """Walk the session VFS subtree and return a paginated tree view.

    The walk root composes from ``sessions/{scoped}/{prefix}`` where
    ``scoped`` is :func:`app.services.uploads._scoped_session_prefix`
    (so multi-tenant deployments scope correctly per #559 / R0.2).

    When ``include_sidecars=False`` (the default), entries under the
    sibling ``sidecars/{scoped}/`` namespace AND any in-tree
    ``.kaos.json`` / ``.meta.json`` paths are dropped from the result
    set. Set ``include_sidecars=True`` to see them (operator-facing
    debug mode).

    Pagination is post-hoc: the underlying walk is one-shot, so
    ``cursor`` is an opaque base10 offset string and ``limit`` is the
    page size (capped at ``_MAX_LIMIT``).
    """
    try:
        normalized_prefix = _normalize_prefix(prefix)
    except VfsPrefixError:
        # Re-raise so the route can translate to 400 — callers should
        # not see internal path strings in the error body.
        raise

    capped_limit = min(max(limit, 1), _MAX_LIMIT)
    scoped = _scoped_session_prefix(session_id, tenant_id)
    session_root = f"sessions/{scoped}/"
    sidecar_root = _sidecar_prefix(session_id, tenant_id)

    walk_root = session_root
    if normalized_prefix:
        walk_root = f"{session_root}{normalized_prefix}/"

    # Lazy import — keeps the module importable without kaos-core at
    # collection time (the test suite injects KaosRuntime via fixture).
    from kaos_core.vfs.models import VFSWalkOptions

    options = VFSWalkOptions(
        max_depth=max_depth,
        include_directories=True,
        patterns=[pattern] if pattern else [],
    )
    walk_result = await runtime.vfs.walk(
        walk_root,
        context_id=session_id,
        options=options,
    )

    # Optionally include the sibling sidecars/ subtree.
    sidecar_walk = None
    if include_sidecars:
        try:
            sidecar_walk = await runtime.vfs.walk(
                sidecar_root,
                context_id=session_id,
                options=options,
            )
        except Exception as exc:  # pragma: no cover — sidecar tree absent on fresh sessions
            logger.debug(
                "vfs.walk(sidecars) failed for session=%s: %s",
                session_id,
                exc,
            )

    raw_entries = list(walk_result.items)
    if sidecar_walk is not None:
        raw_entries.extend(sidecar_walk.items)

    nodes: list[VfsNode] = []
    for entry in raw_entries:
        if entry.error is not None:
            # Carry the error count in the response but don't render
            # broken nodes — the UI gets a footer hint via error_count.
            continue
        node = _entry_to_node(
            path=entry.path,
            metadata=entry.metadata,
            session_root=session_root,
            sidecar_root=sidecar_root,
        )
        if node.is_sidecar and not include_sidecars:
            continue
        nodes.append(node)

    # Stable ordering: files/ before artifacts/ before everything else,
    # then sidecars (when present), then alpha within each group.
    def _sort_key(n: VfsNode) -> tuple[int, str]:
        if n.is_upload:
            return (0, n.relative_path.lower())
        if n.is_artifact:
            return (1, n.relative_path.lower())
        if n.is_sidecar:
            return (3, n.relative_path.lower())
        return (2, n.relative_path.lower())

    nodes.sort(key=_sort_key)

    # Pagination — opaque cursor is just an int offset.
    offset = 0
    if cursor:
        try:
            offset = max(int(cursor), 0)
        except ValueError:
            offset = 0
    page = nodes[offset : offset + capped_limit]
    next_offset = offset + len(page)
    next_cursor = str(next_offset) if next_offset < len(nodes) else None

    # Per-node enrichment runs only on the paged slice — cheap, but
    # don't waste sidecar reads on nodes the caller can't see.
    enriched: list[VfsNode] = []
    for node in page:
        enriched.append(
            await _enrich_upload_node(
                runtime,
                node=node,
                session_id=session_id,
                tenant_id=tenant_id,
            )
        )

    return VfsListResponse(
        session_id=session_id,
        prefix=normalized_prefix,
        nodes=enriched,
        total_count=len(nodes),
        error_count=walk_result.error_count + (sidecar_walk.error_count if sidecar_walk else 0),
        next_cursor=next_cursor,
    )
