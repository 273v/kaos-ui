"""Unit tests for ``app.services.vfs.walk_session_vfs``.

Stage 1 of the 2026-05-26 VFS explorer plan. Tests cover the three
SPA-specific concerns layered over kaos-core's ``VirtualFileSystem.walk``:

1. **Session scoping + path safety.** ``..`` segments rejected; the
   walk root is composed under ``sessions/{scoped}/`` and never
   escapes via caller-supplied ``prefix``.
2. **Sidecar exclusion default-on.** ``.kaos.json`` / ``.meta.json``
   entries (both out-of-tree under ``sidecars/{scoped}/`` and the
   pre-#583 in-tree shape) are hidden unless ``include_sidecars=True``.
3. **Upload enrichment.** Files under ``files/`` join their meta
   sidecars to populate ``parse_status`` + ``summary_excerpt``.

Uses ``KaosRuntime.test_mode()`` for an in-memory GLOBAL-isolated VFS
per `feedback_check_lockfile_not_venv.md`'s isolation-pattern guidance.
"""

from __future__ import annotations

import json

import pytest
from kaos_core import KaosRuntime

from app.services.vfs import (
    VfsPrefixError,
    _normalize_prefix,
    walk_session_vfs,
)


@pytest.fixture
def runtime() -> KaosRuntime:
    """In-memory GLOBAL-isolated runtime — no cross-test leakage."""
    return KaosRuntime.test_mode()


# ── _normalize_prefix --------------------------------------------------


class TestNormalizePrefix:
    """The prefix is the only client-supplied string that lands in a
    VFS walk root, so its sanitization is load-bearing for path-safety.
    """

    def test_empty_is_empty(self) -> None:
        assert _normalize_prefix("") == ""

    def test_none_like_empty(self) -> None:
        # Defensive: empty falsy values normalize to empty without raising.
        assert _normalize_prefix("/") == ""

    def test_strips_leading_slash(self) -> None:
        assert _normalize_prefix("/files") == "files"

    def test_strips_trailing_slash(self) -> None:
        assert _normalize_prefix("files/") == "files"

    def test_collapses_internal_slashes(self) -> None:
        assert _normalize_prefix("files//foo//") == "files/foo"

    def test_rejects_parent_dir(self) -> None:
        with pytest.raises(VfsPrefixError):
            _normalize_prefix("../etc")

    def test_rejects_parent_dir_mid_path(self) -> None:
        with pytest.raises(VfsPrefixError):
            _normalize_prefix("files/../etc")

    def test_rejects_dot_segment(self) -> None:
        with pytest.raises(VfsPrefixError):
            _normalize_prefix("files/./foo")

    def test_rejects_backslash(self) -> None:
        with pytest.raises(VfsPrefixError):
            _normalize_prefix("files\\nasty")


# ── walk_session_vfs ---------------------------------------------------


async def _write(runtime: KaosRuntime, path: str, data: bytes, session_id: str) -> None:
    await runtime.vfs.write(path, data, context_id=session_id)


@pytest.mark.asyncio
async def test_empty_session_returns_empty_tree(runtime: KaosRuntime) -> None:
    result = await walk_session_vfs(runtime, session_id="sid-empty", tenant_id=None)
    assert result.session_id == "sid-empty"
    assert result.nodes == []
    assert result.total_count == 0
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_walks_uploads_and_artifacts(runtime: KaosRuntime) -> None:
    """A session with a user upload + an agent artifact surfaces both."""
    sid = "sid-uploads"
    await _write(runtime, f"sessions/{sid}/files/contract.pdf", b"%PDF-fake-bytes", sid)
    await _write(runtime, f"sessions/{sid}/artifacts/abc-123.json", b'{"hello":"world"}', sid)

    result = await walk_session_vfs(runtime, session_id=sid, tenant_id=None)

    paths = sorted(n.relative_path for n in result.nodes)
    assert "files/contract.pdf" in paths
    assert "artifacts/abc-123.json" in paths

    upload = next(n for n in result.nodes if n.relative_path == "files/contract.pdf")
    assert upload.is_upload is True
    assert upload.is_artifact is False
    assert upload.is_sidecar is False

    artifact = next(n for n in result.nodes if n.relative_path == "artifacts/abc-123.json")
    assert artifact.is_artifact is True
    assert artifact.is_upload is False


@pytest.mark.asyncio
async def test_sidecars_hidden_by_default(runtime: KaosRuntime) -> None:
    """``.kaos.json`` / ``.meta.json`` sidecars in either location stay hidden."""
    sid = "sid-sidecars"
    # Real upload + its out-of-tree sidecars (#583 layout).
    await _write(runtime, f"sessions/{sid}/files/nda.docx", b"PK-fake", sid)
    await _write(
        runtime, f"sidecars/{sid}/nda.docx.meta.json", b'{"parse":{"status":"ready"}}', sid
    )
    await _write(runtime, f"sidecars/{sid}/nda.docx.kaos.json", b'{"body":[]}', sid)
    # Legacy in-tree sidecar (pre-#583).
    await _write(runtime, f"sessions/{sid}/files/legacy.pdf.meta.json", b'{"x":1}', sid)

    default = await walk_session_vfs(runtime, session_id=sid, tenant_id=None)
    rel_paths = {n.relative_path for n in default.nodes}
    # Real file shows up.
    assert "files/nda.docx" in rel_paths
    # Sidecars do NOT show up under either layout when toggle is off.
    assert not any(p.endswith(".meta.json") for p in rel_paths)
    assert not any(p.endswith(".kaos.json") for p in rel_paths)


@pytest.mark.asyncio
async def test_sidecars_visible_when_opted_in(runtime: KaosRuntime) -> None:
    sid = "sid-sidecars-on"
    await _write(runtime, f"sessions/{sid}/files/nda.docx", b"PK-fake", sid)
    await _write(
        runtime, f"sidecars/{sid}/nda.docx.meta.json", b'{"parse":{"status":"ready"}}', sid
    )

    opted_in = await walk_session_vfs(
        runtime, session_id=sid, tenant_id=None, include_sidecars=True
    )
    sidecar_nodes = [n for n in opted_in.nodes if n.is_sidecar]
    assert len(sidecar_nodes) >= 1
    assert any(n.path.endswith(".meta.json") for n in sidecar_nodes)


@pytest.mark.asyncio
async def test_upload_enrichment_populates_parse_status(runtime: KaosRuntime) -> None:
    """When a meta sidecar is readable, the upload node carries parse_status."""
    sid = "sid-enrich"
    await _write(runtime, f"sessions/{sid}/files/contract.pdf", b"%PDF", sid)
    meta = {
        "filename": "contract.pdf",
        "size_bytes": 4,
        "content_type": "application/pdf",
        "parse": {"status": "ready"},
        "summary": "This NDA between Acme and Beta restricts disclosure of confidential terms.",
    }
    await _write(
        runtime,
        f"sidecars/{sid}/contract.pdf.meta.json",
        json.dumps(meta).encode("utf-8"),
        sid,
    )

    result = await walk_session_vfs(runtime, session_id=sid, tenant_id=None)
    upload = next(n for n in result.nodes if n.relative_path == "files/contract.pdf")
    assert upload.parse_status == "ready"
    assert upload.summary_excerpt is not None
    assert "NDA between Acme" in upload.summary_excerpt


@pytest.mark.asyncio
async def test_upload_enrichment_silent_on_missing_sidecar(runtime: KaosRuntime) -> None:
    """No meta sidecar → no enrichment, but the node still surfaces cleanly."""
    sid = "sid-no-meta"
    await _write(runtime, f"sessions/{sid}/files/orphan.pdf", b"%PDF", sid)

    result = await walk_session_vfs(runtime, session_id=sid, tenant_id=None)
    upload = next(n for n in result.nodes if n.relative_path == "files/orphan.pdf")
    assert upload.parse_status is None
    assert upload.summary_excerpt is None


@pytest.mark.asyncio
async def test_pagination(runtime: KaosRuntime) -> None:
    """Cursor-based pagination round-trips through pages of results."""
    sid = "sid-paginate"
    for i in range(7):
        await _write(runtime, f"sessions/{sid}/files/file-{i:02d}.txt", b"x", sid)

    page1 = await walk_session_vfs(runtime, session_id=sid, tenant_id=None, limit=3)
    assert len(page1.nodes) == 3
    assert page1.total_count == 7
    assert page1.next_cursor is not None

    page2 = await walk_session_vfs(
        runtime, session_id=sid, tenant_id=None, limit=3, cursor=page1.next_cursor
    )
    assert len(page2.nodes) == 3
    assert page2.next_cursor is not None

    page3 = await walk_session_vfs(
        runtime, session_id=sid, tenant_id=None, limit=3, cursor=page2.next_cursor
    )
    assert len(page3.nodes) == 1
    assert page3.next_cursor is None


@pytest.mark.asyncio
async def test_prefix_filters_to_subtree(runtime: KaosRuntime) -> None:
    """Passing ``prefix=files`` walks only the uploads subtree."""
    sid = "sid-prefix"
    await _write(runtime, f"sessions/{sid}/files/a.txt", b"a", sid)
    await _write(runtime, f"sessions/{sid}/artifacts/b.json", b"b", sid)

    only_files = await walk_session_vfs(runtime, session_id=sid, tenant_id=None, prefix="files")
    rel = {n.relative_path for n in only_files.nodes}
    assert "files/a.txt" in rel
    assert "artifacts/b.json" not in rel


@pytest.mark.asyncio
async def test_prefix_rejects_escape(runtime: KaosRuntime) -> None:
    """``..`` segments raise VfsPrefixError — the route translates to 400."""
    with pytest.raises(VfsPrefixError):
        await walk_session_vfs(
            runtime, session_id="sid-escape", tenant_id=None, prefix="../../../etc"
        )


@pytest.mark.asyncio
async def test_tenant_scoping_separates_sessions(runtime: KaosRuntime) -> None:
    """Two tenants with the same raw sid see disjoint VFS subtrees."""
    sid = "shared-sid"
    await _write(runtime, f"sessions/alice:{sid}/files/alice.txt", b"alice", sid)
    await _write(runtime, f"sessions/bob:{sid}/files/bob.txt", b"bob", sid)

    alice = await walk_session_vfs(runtime, session_id=sid, tenant_id="alice")
    bob = await walk_session_vfs(runtime, session_id=sid, tenant_id="bob")
    assert any(n.relative_path == "files/alice.txt" for n in alice.nodes)
    assert not any("bob" in n.relative_path for n in alice.nodes)
    assert any(n.relative_path == "files/bob.txt" for n in bob.nodes)
    assert not any("alice" in n.relative_path for n in bob.nodes)


@pytest.mark.asyncio
async def test_uploads_sort_before_artifacts(runtime: KaosRuntime) -> None:
    """Stable sort: uploads → artifacts → other → sidecars."""
    sid = "sid-sort"
    await _write(runtime, f"sessions/{sid}/files/aaa.txt", b"a", sid)
    await _write(runtime, f"sessions/{sid}/artifacts/zzz.json", b"z", sid)

    result = await walk_session_vfs(runtime, session_id=sid, tenant_id=None)
    # The upload (files/aaa.txt) must come before the artifact even
    # though "aaa" < "zzz" alphabetically suggests the same order;
    # this guards the category-first sort.
    rel = [n.relative_path for n in result.nodes]
    assert rel.index("files/aaa.txt") < rel.index("artifacts/zzz.json")
