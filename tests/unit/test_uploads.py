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


# ── bytes-based parser dispatch (spoof resistance) ───────────────────


def _docx_bytes(payload_type: str = "wordprocessingml.document") -> bytes:
    """Build a minimal valid OPC zip recognizable as a DOCX/PPTX/XLSX.

    Mirrors the helper in the upstream kaos-nlp-core test suite — the
    [Content_Types].xml Override is what the detector's OPC fallback
    greps for.
    """
    import io
    import zipfile

    payload_map = {
        "wordprocessingml.document": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            "word/document.xml",
        ),
        "spreadsheetml.sheet": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
            "xl/workbook.xml",
        ),
        "presentationml.presentation": (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
            "ppt/presentation.xml",
        ),
    }
    ct_string, part_name = payload_map[payload_type]
    buf = io.BytesIO()
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/{part_name}" ContentType="{ct_string}"/>'
        "</Types>"
    ).encode()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr(part_name, b"<doc/>")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_parse_sync_dispatches_docx_when_extension_is_pdf() -> None:
    """Spoof-resistance: a DOCX renamed ``report.pdf`` MUST route to the
    DOCX parser (bytes are the source of truth) rather than to
    pypdfium2 (where it would die with an opaque error).

    The audit's primary motivating bug — closes the kaos-ui /
    SPA-backend spoofable-upload class. Skipped when the runtime
    helpers needed to make the dispatch observable aren't available.
    """
    pytest.importorskip("kaos_nlp_core.content_type")
    pytest.importorskip("kaos_office")

    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from kaos_ui.uploads import _parse_sync

    docx = _docx_bytes("wordprocessingml.document")
    with NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(docx)
        temp_path = Path(tf.name)
    try:
        # Declared ext is ".pdf" (the spoof) but bytes are DOCX. The
        # dispatcher should route to parse_docx and return a non-None
        # parsed document, not raise. Some kaos-office versions return
        # a ContentDocument; we only assert "did not raise + returned
        # something".
        result = _parse_sync(temp_path, ".pdf")
        assert result is not None
    finally:
        temp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_parse_sync_refuses_unknown_bytes_with_clear_error() -> None:
    """Detector returned 'unknown' (no magic-byte signature) → refuse
    with a user-friendly error that names both the declared ext and
    the detection failure. Per audit §8 Q2 option b (kaos-ui uploads
    are user-facing; fail fast)."""
    pytest.importorskip("kaos_nlp_core.content_type")

    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from kaos_ui.uploads import _parse_sync

    with NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        # Plain ASCII — no magic bytes anywhere; detector returns "unknown".
        tf.write(b"this is plain text masquerading as a PDF")
        temp_path = Path(tf.name)
    try:
        with pytest.raises(UploadValidationError) as exc:
            _parse_sync(temp_path, ".pdf")
        assert "could not identify content type" in exc.value.what.lower()
        assert ".pdf" in exc.value.what  # declared ext surfaced
    finally:
        temp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_parse_sync_refuses_image_with_clear_error() -> None:
    """Detector recognized the bytes but not as a supported document
    format → refuse with a typed error naming the detected group and
    the declared extension."""
    pytest.importorskip("kaos_nlp_core.content_type")

    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from kaos_ui.uploads import _parse_sync

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # PNG magic
    with NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        tf.write(png_bytes)
        temp_path = Path(tf.name)
    try:
        with pytest.raises(UploadValidationError) as exc:
            _parse_sync(temp_path, ".docx")
        # Error names BOTH the declared ext and the detected group.
        body = (exc.value.what + " " + exc.value.how_to_fix).lower()
        assert ".docx" in body
        assert "image" in body or "png" in body
    finally:
        temp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_parse_sync_falls_back_to_extension_when_nlp_core_missing(monkeypatch) -> None:
    """When ``kaos_nlp_core.content_type`` import fails at runtime we
    must fall through to extension-based dispatch with a logged
    warning — preserves the kaos-ui-without-NLP baseline."""
    pytest.importorskip("kaos_office")

    import builtins
    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from kaos_ui.uploads import _parse_sync

    real_import = builtins.__import__

    def _block_kaos_nlp_core(name, *args, **kwargs):
        if name == "kaos_nlp_core.content_type" or name.startswith("kaos_nlp_core.content_type"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_kaos_nlp_core)

    docx = _docx_bytes("wordprocessingml.document")
    with NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        tf.write(docx)
        temp_path = Path(tf.name)
    try:
        # With NLP core blocked + ext=".docx" matching the bytes, the
        # extension-fallback path routes to parse_docx successfully.
        result = _parse_sync(temp_path, ".docx")
        assert result is not None
    finally:
        temp_path.unlink(missing_ok=True)
