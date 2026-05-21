"""Tests for B0.1 — SessionStore meta tenant scoping (#569).

Pre-B0.1 (broad-reliability roadmap §B0.1) the SessionStore wrote every
session's meta sidecar to ``single-user-chat/sessions/{session_id}/meta.json``
with no tenant prefix. Tenant A could read tenant B's session title,
system prompt, and policy by guessing the ULID — a cross-tenant
confidentiality leak strictly worse than the VFS upload-path leak that
R0.2 closed today (system prompts often carry matter / client / deal
identifiers).

Post-B0.1 the meta path is
``single-user-chat/sessions/{scope_session_id(session_id, tenant_id)}/meta.json``,
mirroring how kaos-agents scopes its own session ids at the API edge
(see ``kaos_agents/api/settings.py:scope_session_id``).

These tests assert:

- The on-disk path differs between two tenants holding the same ULID.
- ``get``, ``patch``, ``touch``, ``archive`` all 404 across tenants.
- ``list`` filters to the caller's slice in auth'd mode and to the
  unscoped slice in localhost-dev mode.
- Localhost-dev mode (``tenant_id=None``) preserves pre-B0.1 layout
  for backward compat with existing on-disk sessions.
"""

from __future__ import annotations

import pytest
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from kaos_core.vfs.models import IsolationMode, StorageBackend

from app.exceptions import SessionNotFoundError
from app.persistence.sessions import SessionStore


def _store() -> SessionStore:
    """Build a fresh in-memory SessionStore for isolated test runs."""
    cfg = VFSConfig(
        isolation_mode=IsolationMode.GLOBAL,
        default_backend=StorageBackend.MEMORY,
    )
    return SessionStore(vfs=VirtualFileSystem(config=cfg))


class TestMetaPathScoping:
    """The internal ``_meta_path`` helper is the load-bearing piece."""

    def test_dev_mode_path_unchanged(self):
        """``tenant_id=None`` → pre-B0.1 layout (backward compat)."""
        s = _store()
        path = s._meta_path("01ABC", tenant_id=None)
        assert path == "single-user-chat/sessions/01ABC/meta.json"

    def test_authd_path_prefixed_with_tenant(self):
        s = _store()
        path = s._meta_path("01ABC", tenant_id="t1")
        assert path == "single-user-chat/sessions/t1:01ABC/meta.json"

    def test_two_tenants_get_distinct_paths_for_same_ulid(self):
        s = _store()
        a = s._meta_path("01ABC", tenant_id="tenant-a")
        b = s._meta_path("01ABC", tenant_id="tenant-b")
        assert a != b
        # Sanity: neither equals the dev-mode (unscoped) path.
        assert a != s._meta_path("01ABC", tenant_id=None)
        assert b != s._meta_path("01ABC", tenant_id=None)

    def test_archived_namespace_also_scoped(self):
        s = _store()
        archived = s._meta_path("01ABC", tenant_id="t1", archived=True)
        assert archived.startswith("single-user-chat/archived/t1:01ABC/")


class TestCrossTenantIsolation:
    """End-to-end: token A can't read / patch / archive token B's session."""

    @pytest.mark.asyncio
    async def test_get_404s_across_tenants(self):
        s = _store()
        sid = "01XYZ"
        # Tenant A creates a session with this id.
        await s.create(
            title="Tenant A confidential",
            model="anthropic:claude-haiku-4-5",
            system_prompt="Internal-only matter prompt — contains client info",
            session_id=sid,
            tenant_id="tenant-a",
        )
        # Tenant B guesses the ULID + tries to read.
        with pytest.raises(SessionNotFoundError):
            await s.get(sid, tenant_id="tenant-b")
        # And localhost-dev mode also gets a 404 (no fallback to scoped).
        with pytest.raises(SessionNotFoundError):
            await s.get(sid, tenant_id=None)

    @pytest.mark.asyncio
    async def test_patch_404s_across_tenants(self):
        s = _store()
        sid = "01XYZ"
        await s.create(
            title="A's session",
            model="m",
            system_prompt="prompt",
            session_id=sid,
            tenant_id="tenant-a",
        )
        with pytest.raises(SessionNotFoundError):
            await s.patch(sid, title="hijacked", tenant_id="tenant-b")

    @pytest.mark.asyncio
    async def test_archive_404s_across_tenants(self):
        s = _store()
        sid = "01XYZ"
        await s.create(
            title="A's session",
            model="m",
            system_prompt="prompt",
            session_id=sid,
            tenant_id="tenant-a",
        )
        with pytest.raises(SessionNotFoundError):
            await s.archive(sid, tenant_id="tenant-b")

    @pytest.mark.asyncio
    async def test_touch_404s_across_tenants(self):
        s = _store()
        sid = "01XYZ"
        await s.create(
            title="A's session",
            model="m",
            system_prompt="prompt",
            session_id=sid,
            tenant_id="tenant-a",
        )
        with pytest.raises(SessionNotFoundError):
            await s.touch(sid, tenant_id="tenant-b")

    @pytest.mark.asyncio
    async def test_same_ulid_distinct_metas_persist_per_tenant(self):
        """Two tenants happen to choose (or guess) the same ULID — both
        sessions persist independently with their own meta."""
        s = _store()
        sid = "01COLLIDE"
        await s.create(
            title="A's session",
            model="m-a",
            system_prompt="a's prompt",
            session_id=sid,
            tenant_id="tenant-a",
        )
        await s.create(
            title="B's session",
            model="m-b",
            system_prompt="b's prompt",
            session_id=sid,
            tenant_id="tenant-b",
        )

        meta_a = await s.get(sid, tenant_id="tenant-a")
        meta_b = await s.get(sid, tenant_id="tenant-b")

        assert meta_a.title == "A's session"
        assert meta_b.title == "B's session"
        assert meta_a.model == "m-a"
        assert meta_b.model == "m-b"
        assert meta_a.system_prompt != meta_b.system_prompt


class TestListFiltering:
    """``list()`` returns only the caller's slice."""

    @pytest.mark.asyncio
    async def test_list_filters_to_calling_tenant(self):
        s = _store()
        await s.create(
            title="A1", model="m", system_prompt="p", tenant_id="tenant-a"
        )
        await s.create(
            title="A2", model="m", system_prompt="p", tenant_id="tenant-a"
        )
        await s.create(
            title="B1", model="m", system_prompt="p", tenant_id="tenant-b"
        )

        a_summaries, _ = await s.list(tenant_id="tenant-a")
        b_summaries, _ = await s.list(tenant_id="tenant-b")

        a_titles = {summary.title for summary in a_summaries}
        b_titles = {summary.title for summary in b_summaries}

        assert a_titles == {"A1", "A2"}
        assert b_titles == {"B1"}
        assert "B1" not in a_titles  # tenant A cannot see B's session
        assert "A1" not in b_titles
        assert "A2" not in b_titles

    @pytest.mark.asyncio
    async def test_dev_mode_list_excludes_tenant_scoped_entries(self):
        """Localhost-dev mode (``tenant_id=None``) only shows unscoped
        entries — so the operator's own list isn't contaminated by
        tenant-scoped sessions written by a prior auth'd run on the
        same disk."""
        s = _store()
        await s.create(
            title="dev session", model="m", system_prompt="p", tenant_id=None
        )
        await s.create(
            title="tenant session",
            model="m",
            system_prompt="p",
            tenant_id="tenant-a",
        )

        dev_summaries, _ = await s.list(tenant_id=None)
        titles = {summary.title for summary in dev_summaries}
        assert titles == {"dev session"}
        assert "tenant session" not in titles

    @pytest.mark.asyncio
    async def test_empty_list_when_tenant_has_no_sessions(self):
        s = _store()
        await s.create(title="A", model="m", system_prompt="p", tenant_id="tenant-a")
        summaries, _ = await s.list(tenant_id="tenant-b")
        assert summaries == []


class TestDevModeBackwardCompat:
    """Localhost-dev mode (no auth) preserves the pre-B0.1 layout."""

    @pytest.mark.asyncio
    async def test_dev_mode_create_get_round_trip(self):
        s = _store()
        sid = "01DEV"
        await s.create(
            title="dev",
            model="m",
            system_prompt="p",
            session_id=sid,
            tenant_id=None,
        )
        # Path stays unscoped.
        assert s._meta_path(sid) == f"single-user-chat/sessions/{sid}/meta.json"
        meta = await s.get(sid, tenant_id=None)
        assert meta.title == "dev"

    @pytest.mark.asyncio
    async def test_dev_mode_patch_persists(self):
        s = _store()
        sid = "01DEV"
        await s.create(
            title="dev", model="m", system_prompt="p", session_id=sid, tenant_id=None
        )
        await s.patch(sid, title="dev-renamed", tenant_id=None)
        meta = await s.get(sid, tenant_id=None)
        assert meta.title == "dev-renamed"
