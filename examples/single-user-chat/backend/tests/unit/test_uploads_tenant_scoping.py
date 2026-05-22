"""Tests for R0.2 — upload pipeline tenant-scopes VFS paths.

The bug (kaos-modules/docs/plans/2026-05-21-reliability-roadmap.md § R0.2):
SPA file uploads landed at ``sessions/{raw_sid}/files/{name}`` while the
kaos-agents Runner read from ``sessions/{tenant}:{raw_sid}/files/{name}``
(kaos-agents' POST handler applies ``scope_session_id`` at the API edge).
Auth'd users could upload PDFs that the agent could never find, and ReAct
loops would spiral on missing paths.

The fix: ``_vfs_path`` and ``_vfs_prefix`` accept a ``tenant_id`` and apply
``scope_session_id`` so the writer namespace matches the reader namespace.
Route handlers obtain ``tenant_id`` from ``require_auth`` and thread it
through every upload-pipeline call.
"""

from __future__ import annotations

import pytest

from app.services.uploads import _scoped_session_prefix, _vfs_path, _vfs_prefix


class TestScopedSessionPrefix:
    """``_scoped_session_prefix`` mirrors kaos-agents' ``scope_session_id``."""

    def test_localhost_dev_mode_returns_raw_session_id(self):
        """``tenant_id=None`` (localhost-dev) → no scoping."""
        assert _scoped_session_prefix("sid-abc", None) == "sid-abc"

    def test_authd_tenant_prefixes_session_id_with_colon(self):
        """``tenant_id="t1"`` → ``"t1:sid-abc"`` to match kaos-agents' scope."""
        assert _scoped_session_prefix("sid-abc", "t1") == "t1:sid-abc"

    def test_empty_session_id_stays_empty(self):
        """Defensive: empty sid pass-through (matches scope_session_id)."""
        assert _scoped_session_prefix("", "t1") == ""

    def test_tenant_separation(self):
        """Two tenants with the SAME raw sid get distinct namespaces."""
        a = _scoped_session_prefix("shared-sid", "tenant-a")
        b = _scoped_session_prefix("shared-sid", "tenant-b")
        assert a != b
        assert a == "tenant-a:shared-sid"
        assert b == "tenant-b:shared-sid"


class TestVfsPath:
    """``_vfs_path`` puts uploads where the agent reads them."""

    def test_no_tenant_matches_legacy_layout(self):
        """Default (``tenant_id=None``) preserves the pre-R0.2 on-disk layout."""
        path = _vfs_path("sid-abc", "doc.pdf")
        assert path == "sessions/sid-abc/files/doc.pdf"

    def test_tenant_scoping_matches_agents_namespace(self):
        """With a tenant, the SPA writer matches the agent's reader namespace.

        kaos-agents' server scopes the session id at server.py:393 to
        ``f"{tenant}:{raw_sid}"`` before passing it to Runner.run(). The
        SPA monkey-patch at ``app/main.py:67`` then builds a KaosContext
        with ``default_vfs_namespace = f"sessions/{scoped_sid}/files/"``.
        Uploads must land at the same prefix so bare-name tool lookups
        resolve.
        """
        path = _vfs_path("sid-abc", "doc.pdf", tenant_id="t1")
        assert path == "sessions/t1:sid-abc/files/doc.pdf"

    def test_two_tenants_get_isolated_paths_for_same_filename(self):
        """Cross-tenant file isolation: same filename → different paths."""
        a = _vfs_path("shared-sid", "report.pdf", tenant_id="tenant-a")
        b = _vfs_path("shared-sid", "report.pdf", tenant_id="tenant-b")
        assert a != b

    def test_filename_passes_through_verbatim(self):
        """Filename is not modified by tenant-scoping."""
        path = _vfs_path("sid", "EMNA Mutual NDA.docx", tenant_id="t1")
        assert path.endswith("/EMNA Mutual NDA.docx")


class TestVfsPrefix:
    """``_vfs_prefix`` is what ``list_session_files`` walks."""

    def test_no_tenant_matches_legacy_prefix(self):
        assert _vfs_prefix("sid-abc", None) == "sessions/sid-abc/files/"

    def test_tenant_scoping(self):
        assert _vfs_prefix("sid-abc", "t1") == "sessions/t1:sid-abc/files/"

    def test_prefix_is_a_path_prefix_of_vfs_path(self):
        """``_vfs_prefix(s, t)`` must prefix every ``_vfs_path(s, *, t)`` result."""
        prefix = _vfs_prefix("sid", "t1")
        path = _vfs_path("sid", "doc.pdf", tenant_id="t1")
        assert path.startswith(prefix)


class TestReaderWriterAlignment:
    """Integration: the SPA's writer namespace matches the agent's reader namespace.

    The reader is kaos-agents' monkey-patched ``_build_internal_agent``
    (see ``app/main.py:67-79``), which sets:
        namespace = f"sessions/{session_id}/files/"
    where ``session_id`` is whatever kaos-agents passes — and kaos-agents
    passes the **scoped** session_id (server.py:393 applies
    ``scope_session_id(session_id, tenant_id)``).

    The writer is the SPA's upload pipeline. Pre-R0.2 it ignored
    ``tenant_id`` and wrote at ``sessions/{raw_sid}/files/``. Post-R0.2
    it threads ``tenant_id`` through and writes at the scoped prefix.

    The reader and writer namespaces MUST match for any tool to find a
    SPA-uploaded file.
    """

    @pytest.mark.parametrize(
        ("session_id", "tenant_id"),
        [
            ("sid-1", None),  # localhost-dev mode
            ("sid-1", "t1"),  # single-tenant prod
            ("sid-1", "tenant-a"),  # multi-tenant prod (tenant A)
            ("sid-1", "tenant-b"),  # multi-tenant prod (tenant B)
        ],
    )
    def test_writer_prefix_equals_reader_namespace(self, session_id, tenant_id):
        """The path the writer (uploads service) chooses must equal the
        ``default_vfs_namespace`` the reader (Runner) sets up.

        The reader builds its namespace from the **already-scoped**
        session_id (kaos-agents scopes at the route boundary). We mirror
        that here by passing the scoped form through to the namespace
        builder.
        """
        # Reader side — what main.py:72 produces, given the scoped id
        # kaos-agents would hand the Runner.
        from kaos_agents.api.settings import scope_session_id

        scoped = scope_session_id(session_id, tenant_id)
        reader_namespace = f"sessions/{scoped}/files/"

        # Writer side — what _vfs_prefix produces (R0.2 fix).
        writer_prefix = _vfs_prefix(session_id, tenant_id)

        assert writer_prefix == reader_namespace, (
            "writer prefix must equal reader namespace for any "
            "bare-name tool lookup to succeed"
        )
