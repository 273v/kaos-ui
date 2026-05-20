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
from app.models import (
    Persona,
    SessionMeta,
    SessionPolicyWire,
    SessionSummary,
    SessionToolSetWire,
    with_denied_floor,
)

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

        ``tools_enabled`` is back-compat sugar: maps to a default
        ceiling (``True``) or to a fully-blocked ceiling (``False``).
        Callers wanting per-group control should mutate ``tool_set``
        via :meth:`patch` after creation.
        """
        sid = session_id or new_session_id()
        # Translate the legacy boolean knob into the new SessionPolicyWire.
        # `tools_enabled=True` → research persona default (8 groups);
        # `tools_enabled=False` → ceiling collapsed to empty.
        if tools_enabled:
            policy = SessionPolicyWire.for_persona("research")
        else:
            # Block-all: drop the ceiling but KEEP the recursion-guard
            # deny floor. A user who flips tools off then back on later
            # via the settings sheet must never lose the kaos-agent-*
            # exclusion.
            policy = SessionPolicyWire(
                allowed_groups=[],
                soft_ceiling=[],
                denied_tools=with_denied_floor([]),
                persona="research",
            )
        # P3-10: stamp the running build's identity so the SPA can
        # badge older sessions as "predates current build."
        from app.routers.health import current_build_sha

        meta = SessionMeta(
            id=sid,
            title=title,
            model=model,
            system_prompt=system_prompt,
            policy=policy,
            created_at=_now(),
            last_message_at=None,
            message_count=0,
            archived=False,
            build_sha=current_build_sha(),
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
        """Return sessions newest-first.

        Single-user scale stays comfortably below the slow-path threshold
        (a few thousand at most), so we read every meta, sort by
        last_message_at, then slice. A cursor is the int offset of the
        next item; a None cursor means start at 0.
        """
        ns = _ARCHIVED_NS if archived else _NS
        all_paths = await self._vfs.list(ns)
        summaries: list[SessionSummary] = []
        for path in all_paths:
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
                    starred=meta.starred,
                    title_source=meta.title_source,
                    build_sha=meta.build_sha,
                    last_turn_cost_usd=meta.last_turn_cost_usd,
                    total_cost_usd=meta.total_cost_usd,
                    total_tokens=meta.total_tokens,
                )
            )
        # Newest first by activity, falling back to created_at.
        summaries.sort(
            key=lambda s: s.last_message_at or s.created_at,
            reverse=True,
        )
        # Apply cursor + limit slice. Cursor is an int-as-string offset
        # so it survives JSON round-trip in the API response.
        start = 0
        if cursor:
            try:
                start = max(0, int(cursor))
            except ValueError:
                start = 0
        end = start + limit
        page = summaries[start:end]
        next_cursor = str(end) if end < len(summaries) else None
        return page, next_cursor

    async def patch(
        self,
        session_id: str,
        *,
        title: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        tools_enabled: bool | None = None,
        tool_set: SessionToolSetWire | None = None,
        policy: SessionPolicyWire | None = None,
        starred: bool | None = None,
        title_source: str | None = None,
        title_updated_at: datetime | None = None,
        # P1-3 cost telemetry. ``last_turn_*`` overwrite; ``total_*``
        # are absolute values the caller computed by reading the prior
        # SessionMeta and adding the turn delta. Keeping the
        # ``patch`` semantics consistent (caller provides the new
        # value, store doesn't compute) avoids races where two
        # concurrent turns each read the same prior total and write
        # back independently.
        last_turn_cost_usd: float | None = None,
        last_turn_tokens: int | None = None,
        total_cost_usd: float | None = None,
        total_tokens: int | None = None,
    ) -> SessionMeta:
        meta = await self._read_meta(session_id)
        updates: dict[str, object] = {}
        if title is not None:
            updates["title"] = title
            # Title patches that come through the public route are
            # treated as MANUAL unless the caller explicitly says
            # otherwise (the auto-titler passes `title_source="auto"`).
            if title_source is None:
                updates["title_source"] = "manual"
        if model is not None:
            updates["model"] = model
        if system_prompt is not None:
            updates["system_prompt"] = system_prompt
        # Three accepted shapes for the tool-policy patch, in
        # decreasing-explicit priority:
        #   1. `policy` (SessionPolicyWire) — the canonical AgenticLoop shape
        #   2. `tool_set` (SessionToolSetWire) — back-compat; rewritten as a
        #      policy update preserving the existing persona / soft_ceiling
        #   3. `tools_enabled` (bool) — legacy sugar; full-on or full-off
        if policy is not None:
            # Force the recursion-guard floor on any policy patch — the
            # caller may have round-tripped through a SessionPolicyWire
            # that lost it (older SPA client, manual API caller, etc).
            updates["policy"] = policy.model_copy(
                update={"denied_tools": with_denied_floor(policy.denied_tools)}
            )
        elif tool_set is not None:
            # Preserve persona + soft_ceiling + loop knobs from the existing
            # meta — the caller only sent the ceiling fragment.
            updates["policy"] = meta.policy.model_copy(
                update={
                    "allowed_groups": list(tool_set.allowed_groups),
                    "denied_tools": with_denied_floor(list(tool_set.denied_tools)),
                    "auto_narrow": tool_set.auto_narrow,
                }
            )
        elif tools_enabled is not None:
            if tools_enabled:
                updates["policy"] = SessionPolicyWire.for_persona("research")
            else:
                updates["policy"] = SessionPolicyWire(
                    allowed_groups=[],
                    soft_ceiling=[],
                    denied_tools=with_denied_floor([]),
                    persona="research",
                )
        if starred is not None:
            updates["starred"] = starred
        if title_source is not None:
            updates["title_source"] = title_source
        if title_updated_at is not None:
            updates["title_updated_at"] = title_updated_at
        if last_turn_cost_usd is not None:
            updates["last_turn_cost_usd"] = last_turn_cost_usd
        if last_turn_tokens is not None:
            updates["last_turn_tokens"] = last_turn_tokens
        if total_cost_usd is not None:
            updates["total_cost_usd"] = total_cost_usd
        if total_tokens is not None:
            updates["total_tokens"] = total_tokens
        new_meta = meta.model_copy(update=updates)
        await self._write_meta(new_meta)
        return new_meta

    async def set_tool_preset(self, session_id: str, preset_name: Persona) -> SessionMeta:
        """Apply a named persona preset to a session.

        Convenience method the SPA's persona-chip row calls. Resets
        both `allowed_groups` AND `soft_ceiling` to the persona's
        defaults (per `kaos_agents.types.session_policy.SessionPolicy.for_persona`).
        """
        return await self.patch(session_id, policy=SessionPolicyWire.for_persona(preset_name))

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
