"""Session metadata sidecar — title, model, system prompt, tools toggle.

Backed by `kaos_core.vfs.VirtualFileSystem` at
`.kaos-vfs/single-user-chat/sessions/{id}/meta.json`. Lives alongside
the kaos-agents agent memory namespace at `.kaos-vfs/kaos-agents/`.

The kaos-agents `POST /v1/sessions` accepts only `session_id` and
discards extra fields (see docs/PATTERNS.md P-003), so we own all
human-facing metadata here. The id is shared with kaos-agents — same
ULID names our `meta.json` AND its memory directory.

All methods are async because `VirtualFileSystem` is async.
"""

from __future__ import annotations

import builtins
from datetime import UTC, datetime

import ulid
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from kaos_core.vfs.models import IsolationMode

from app.exceptions import SessionNotFoundError
from app.models import SessionMeta, SessionSummary

_NS = "single-user-chat/sessions"
_ARCHIVED_NS = "single-user-chat/archived"


def new_session_id() -> str:
    """Generate a new ULID-shaped session id (sortable + URL-safe)."""
    return str(ulid.new())


def _now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    """CRUD over the metadata sidecar.

    Construct one per process — `vfs` holds an internal cache so
    re-using the instance is more efficient than building fresh ones.
    """

    def __init__(self, vfs: VirtualFileSystem | None = None) -> None:
        if vfs is None:
            # Default: GLOBAL isolation so all chat sessions share one
            # flat namespace under `.kaos-vfs/single-user-chat/`.
            cfg = VFSConfig(isolation_mode=IsolationMode.GLOBAL)
            vfs = VirtualFileSystem(config=cfg)
        self._vfs = vfs

    # ── paths ──────────────────────────────────────────────────────

    def _meta_path(self, session_id: str, *, archived: bool = False) -> str:
        ns = _ARCHIVED_NS if archived else _NS
        return f"{ns}/{session_id}/meta.json"

    # ── primitives ────────────────────────────────────────────────

    async def _write_meta(self, meta: SessionMeta, *, archived: bool = False) -> None:
        path = self._meta_path(meta.id, archived=archived)
        data = meta.model_dump_json().encode("utf-8")
        await self._vfs.write(path, data)

    async def _read_meta(self, session_id: str) -> SessionMeta:
        path = self._meta_path(session_id)
        if not await self._vfs.exists(path):
            raise SessionNotFoundError(
                f"Session {session_id!r} not found.\n"
                "How to fix: create the session first with POST /v1/chat/sessions.\n"
                "Alternative: GET /v1/chat/sessions to enumerate available ids."
            )
        raw = await self._vfs.read(path)
        return SessionMeta.model_validate_json(raw)

    # ── public API ────────────────────────────────────────────────

    async def create(
        self,
        *,
        title: str,
        model: str,
        system_prompt: str,
        tools_enabled: bool = False,
        session_id: str | None = None,
    ) -> SessionMeta:
        """Create a new session metadata record. Returns the stored meta.

        Caller is responsible for creating the matching kaos-agents
        session (POST /v1/sessions with this same id). The two sides
        share the id but maintain separate state.
        """
        sid = session_id or new_session_id()
        meta = SessionMeta(
            id=sid,
            title=title,
            model=model,
            system_prompt=system_prompt,
            tools_enabled=tools_enabled,
            created_at=_now(),
            last_message_at=None,
            message_count=0,
            archived=False,
        )
        await self._write_meta(meta)
        return meta

    async def get(self, session_id: str) -> SessionMeta:
        return await self._read_meta(session_id)

    async def list(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        archived: bool = False,
    ) -> tuple[builtins.list[SessionSummary], str | None]:
        ns = _ARCHIVED_NS if archived else _NS
        page = await self._vfs.list_page(ns, cursor=cursor, limit=limit)
        summaries: list[SessionSummary] = []
        for path in page.items:
            # path looks like single-user-chat/sessions/{id}/meta.json
            try:
                raw = await self._vfs.read(path)
                meta = SessionMeta.model_validate_json(raw)
            except Exception:
                # Skip malformed entries silently — the UI can still
                # render the rest. We log at the route layer.
                continue
            summaries.append(
                SessionSummary(
                    id=meta.id,
                    title=meta.title,
                    model=meta.model,
                    last_message_at=meta.last_message_at,
                    created_at=meta.created_at,
                    message_count=meta.message_count,
                    archived=meta.archived,
                )
            )
        # Newest first.
        summaries.sort(
            key=lambda s: s.last_message_at or s.created_at,
            reverse=True,
        )
        return summaries, page.next_cursor

    async def patch(
        self,
        session_id: str,
        *,
        title: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        tools_enabled: bool | None = None,
    ) -> SessionMeta:
        meta = await self._read_meta(session_id)
        updates: dict[str, object] = {}
        if title is not None:
            updates["title"] = title
        if model is not None:
            updates["model"] = model
        if system_prompt is not None:
            updates["system_prompt"] = system_prompt
        if tools_enabled is not None:
            updates["tools_enabled"] = tools_enabled
        new_meta = meta.model_copy(update=updates)
        await self._write_meta(new_meta)
        return new_meta

    async def touch(
        self,
        session_id: str,
        *,
        last_message_at: datetime | None = None,
        increment_messages: int = 0,
    ) -> SessionMeta:
        meta = await self._read_meta(session_id)
        new_meta = meta.model_copy(
            update={
                "last_message_at": last_message_at or _now(),
                "message_count": meta.message_count + increment_messages,
            }
        )
        await self._write_meta(new_meta)
        return new_meta

    async def archive(self, session_id: str) -> datetime:
        """Move metadata under archived/. Idempotent."""
        import contextlib

        meta = await self._read_meta(session_id)
        archived_at = _now()
        new_meta = meta.model_copy(update={"archived": True})
        await self._write_meta(new_meta, archived=True)
        # Best-effort delete of the active path. If it fails (race with
        # another writer), the archived copy still exists.
        with contextlib.suppress(Exception):
            await self._vfs.delete(self._meta_path(session_id))
        return archived_at
