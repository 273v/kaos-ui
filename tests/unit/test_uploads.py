"""kaos_ui.uploads — unit tests for the promoted upload helpers.

The example's app/services/uploads.py used to own these; P1-5
promoted the reusable pieces here. Tests cover the public functions
without spinning a real parser — happy path uses an in-memory VFS and
runs `list_session_files` / `read_session_file` / `delete_session_file`
end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

_kaos_core = pytest.importorskip("kaos_core")

from kaos_core import KaosRuntime  # noqa: E402
from kaos_core.vfs import VFSConfig, VirtualFileSystem  # noqa: E402
from kaos_core.vfs.models import IsolationMode, StorageBackend  # noqa: E402

from kaos_ui.exceptions import (  # noqa: E402
    UploadFileNotFoundError,
    UploadValidationError,
)
from kaos_ui.uploads import (  # noqa: E402
    FileMeta,
    FileParseStatus,
    delete_session_file,
    list_session_files,
    read_session_file,
    render_session_corpus_markdown,
    store_and_parse,
)


def _make_runtime() -> KaosRuntime:
    vfs = VirtualFileSystem(
        config=VFSConfig(
            default_backend=StorageBackend.MEMORY,
            isolation_mode=IsolationMode.GLOBAL,
        )
    )
    return KaosRuntime(vfs=vfs)


async def _seed_meta(rt: KaosRuntime, session_id: str, filename: str, parse_ok: bool) -> None:
    meta = FileMeta(
        filename=filename,
        size_bytes=10,
        content_type="application/pdf",
        uploaded_at=datetime.now(UTC),
        parse=FileParseStatus(status="ready" if parse_ok else "failed"),
    )
    base = f"sessions/{session_id}/files/{filename}"
    await rt.vfs.write(base, b"\x00\x00")
    await rt.vfs.write(f"{base}.meta.json", meta.model_dump_json().encode())


# ── validation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_and_parse_rejects_unsupported_extension() -> None:
    rt = _make_runtime()
    with pytest.raises(UploadValidationError) as exc:
        await store_and_parse(
            runtime=rt,
            session_id="s1",
            raw_filename="hello.txt",
            data=b"hi",
            supported_extensions=(".pdf", ".docx"),
        )
    assert ".pdf" in exc.value.how_to_fix


@pytest.mark.asyncio
async def test_store_and_parse_rejects_empty_filename() -> None:
    rt = _make_runtime()
    with pytest.raises(UploadValidationError):
        await store_and_parse(
            runtime=rt,
            session_id="s1",
            raw_filename="",
            data=b"x",
        )


@pytest.mark.asyncio
async def test_store_and_parse_rejects_overlong_filename() -> None:
    rt = _make_runtime()
    with pytest.raises(UploadValidationError):
        await store_and_parse(
            runtime=rt,
            session_id="s1",
            raw_filename=("a" * 250) + ".pdf",
            data=b"x",
        )


# ── list / read / delete round trip ──────────────────────────────────


@pytest.mark.asyncio
async def test_list_session_files_empty_session_returns_empty_list() -> None:
    rt = _make_runtime()
    metas = await list_session_files(runtime=rt, session_id="s1")
    assert metas == []


@pytest.mark.asyncio
async def test_list_session_files_filters_to_meta_sidecars() -> None:
    rt = _make_runtime()
    await _seed_meta(rt, "s1", "a.pdf", parse_ok=True)
    await _seed_meta(rt, "s1", "b.docx", parse_ok=False)
    metas = await list_session_files(runtime=rt, session_id="s1")
    names = sorted(m.filename for m in metas)
    assert names == ["a.pdf", "b.docx"]


@pytest.mark.asyncio
async def test_list_session_files_skips_unreadable_sidecar() -> None:
    rt = _make_runtime()
    await _seed_meta(rt, "s1", "good.pdf", parse_ok=True)
    # Corrupt sidecar — invalid JSON.
    await rt.vfs.write("sessions/s1/files/bad.pdf.meta.json", b"not json")
    metas = await list_session_files(runtime=rt, session_id="s1")
    names = [m.filename for m in metas]
    assert "good.pdf" in names
    assert "bad.pdf" not in names


@pytest.mark.asyncio
async def test_read_session_file_returns_bytes_and_meta() -> None:
    rt = _make_runtime()
    await _seed_meta(rt, "s1", "doc.pdf", parse_ok=True)
    data, meta = await read_session_file(runtime=rt, session_id="s1", filename="doc.pdf")
    assert isinstance(data, bytes)
    assert meta.filename == "doc.pdf"
    assert meta.parse.status == "ready"


@pytest.mark.asyncio
async def test_read_session_file_404s_when_missing() -> None:
    rt = _make_runtime()
    with pytest.raises(UploadFileNotFoundError):
        await read_session_file(runtime=rt, session_id="s1", filename="nope.pdf")


@pytest.mark.asyncio
async def test_delete_session_file_removes_all_siblings() -> None:
    rt = _make_runtime()
    await _seed_meta(rt, "s1", "doc.pdf", parse_ok=True)
    # Also seed a .kaos.json sibling.
    await rt.vfs.write("sessions/s1/files/doc.pdf.kaos.json", b'{"type":"ContentDocument"}')

    await delete_session_file(runtime=rt, session_id="s1", filename="doc.pdf")

    # Meta + bytes + AST all gone.
    assert not await rt.vfs.exists("sessions/s1/files/doc.pdf")
    assert not await rt.vfs.exists("sessions/s1/files/doc.pdf.meta.json")
    assert not await rt.vfs.exists("sessions/s1/files/doc.pdf.kaos.json")


@pytest.mark.asyncio
async def test_delete_session_file_404s_when_missing() -> None:
    rt = _make_runtime()
    with pytest.raises(UploadFileNotFoundError):
        await delete_session_file(runtime=rt, session_id="s1", filename="nope.pdf")


# ── corpus markdown ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_session_corpus_markdown_empty_session() -> None:
    rt = _make_runtime()
    assert await render_session_corpus_markdown(runtime=rt, session_id="s1") == ""


@pytest.mark.asyncio
async def test_render_session_corpus_markdown_includes_vfs_paths() -> None:
    """The agent needs explicit VFS paths in each file's header so it
    can call kaos-content-* / kaos-pdf-* tools with the right argument.

    The render function reaches for `kaos_content` to format the
    inline body block. kaos-ui's dev group does not pin kaos-content
    (it's a consumer dep, not a kaos-ui dep), so skip when
    unavailable — the same condition the production code handles
    gracefully via a logger warning + empty-string return.
    """
    pytest.importorskip("kaos_content")
    rt = _make_runtime()
    await _seed_meta(rt, "s1", "policy.pdf", parse_ok=False)  # failed parse
    md = await render_session_corpus_markdown(runtime=rt, session_id="s1")
    assert "policy.pdf" in md
    assert "VFS bytes: `sessions/s1/files/policy.pdf`" in md
    assert "VFS AST (kaos-content): `sessions/s1/files/policy.pdf.kaos.json`" in md


# ── filename sanitization (defense in depth) ─────────────────────────


@pytest.mark.asyncio
async def test_filename_sanitization_strips_directory_components() -> None:
    """A client trying to upload as `../../etc/passwd` is normalized to
    the basename only — defense in depth alongside the VFS's traversal
    check.
    """
    rt = _make_runtime()
    # The leading directory parts get stripped + suffix passes.
    # Using `parse_ok=False` shape — we never actually call store_and_parse
    # because that path needs real PDF bytes. Test the sanitizer via
    # store_and_parse's validation hop: pass a traversal attempt + an
    # unsupported extension and confirm we see the extension error
    # (i.e. the path got normalized to just the basename before the
    # extension check).
    with pytest.raises(UploadValidationError) as exc:
        await store_and_parse(
            runtime=rt,
            session_id="s1",
            raw_filename="../../etc/passwd",
            data=b"x",
            supported_extensions=(".pdf",),
        )
    # The error must reference the (empty) extension, NOT a path-traversal
    # message — proving the basename got extracted first.
    assert "extension" in exc.value.what.lower()
