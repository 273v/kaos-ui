"""File upload + parse pipeline for kaos-agents-on-FastAPI apps.

P1-5: promotes the helpers that lived in
``examples/single-user-chat/backend/app/services/uploads.py`` so that
every kaos-agents-on-FastAPI app doesn't have to re-implement the
"save bytes + parse + persist .meta.json sidecar" pipeline.

Public surface (see :data:`__all__` at the bottom):

- :func:`store_and_parse` — accept bytes, persist the original at a
  predictable VFS path, dispatch a parser by extension (PDF / DOCX /
  PPTX), persist the parsed AST + a per-file metadata sidecar.
- :func:`list_session_files` — walk the per-session prefix and load
  every ``.meta.json`` into a list of :class:`FileMeta` records.
- :func:`read_session_file` — retrieve original bytes + meta for one
  file.
- :func:`delete_session_file` — remove original bytes + AST + meta.
- :func:`render_session_corpus_markdown` — build the per-turn corpus
  block the chat router inlines into the agent's system prompt.
- :func:`backfill_session_files` — recompute token_count + summary
  for ready-parsed files that are missing them.

The exception hierarchy (:class:`UploadError` and subclasses) lives in
:mod:`kaos_ui.exceptions` so callers translating to HTTP can import
just the types they raise.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from kaos_core import KaosRuntime
from kaos_core.logging import get_logger
from pydantic import BaseModel

from kaos_ui.exceptions import (
    UploadFileNotFoundError,
    UploadParseError,
    UploadValidationError,
)

logger = get_logger("kaos.ui.uploads")


# Single-worker executor. PDFium holds a global C lock; the other
# parsers are sync but happy to be serialized too. Keeps semantics
# predictable across concurrent uploads without a thread pool size
# that varies by host.
_PARSER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kaos-ui-upload-parser")


# ── value types ──────────────────────────────────────────────────────


class FileParseStatus(BaseModel):
    """Parse outcome for one uploaded file.

    ``ready`` means the file was parsed and a ``.kaos.json`` AST
    sidecar exists in the VFS alongside the original bytes.
    ``failed`` means parsing raised — the original bytes were still
    saved.
    """

    status: Literal["ready", "failed"]
    error: str | None = None


class FileMeta(BaseModel):
    """Per-file metadata persisted alongside the upload in the VFS.

    Lives at ``sessions/{session_id}/files/{filename}.meta.json``.
    Mirror this shape into your application's API response model
    rather than re-deriving it from scratch.
    """

    filename: str
    size_bytes: int
    content_type: str | None = None
    uploaded_at: datetime
    parse: FileParseStatus
    # Populated post-parse via kaos-nlp-core + kaos-llm-core. Both are
    # best-effort — a parse failure or summarizer outage leaves them
    # null, but the file is still persisted.
    token_count: int | None = None
    summary: str | None = None
    # B0.4 / B0.5 — surface honest parse-mode signals so the UI can
    # render banners ("This PDF was OCR'd — text accuracy may vary",
    # "This DOCX contains tracked changes — review insertions/deletions"
    # before relying on the agent's analysis). Both default to False so
    # legacy meta sidecars round-trip without re-parsing.
    ocr_applied: bool = False
    track_changes_detected: bool = False


# ── filename sanitization ────────────────────────────────────────────


_MAX_FILENAME_LEN = 200
_ALLOWED_FILENAME_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-+ ",
)


def _safe_filename(raw: str) -> str:
    """Strip directory components + bound length + restrict charset.

    Defense in depth — the VFS itself rejects ``..`` traversal, but
    we still normalize at the boundary so the on-disk path is
    predictable.
    """
    base = Path(raw).name  # drop any directory the client snuck in
    if not base or base in (".", ".."):
        raise UploadValidationError(
            what=f"invalid filename: {raw!r}",
            how_to_fix="upload a file with a non-empty name",
        )
    if len(base) > _MAX_FILENAME_LEN:
        raise UploadValidationError(
            what=f"filename longer than {_MAX_FILENAME_LEN} chars: {base[:30]!r}…",
            how_to_fix=f"rename the file to <= {_MAX_FILENAME_LEN} characters",
        )
    cleaned = "".join(c if c in _ALLOWED_FILENAME_CHARS else "_" for c in base)
    return cleaned


def _vfs_path(session_id: str, filename: str) -> str:
    """Canonical per-session upload location used by every helper here."""
    return f"sessions/{session_id}/files/{filename}"


# ── parser dispatch ──────────────────────────────────────────────────


_BYTES_GROUP_TO_EXT: dict[str, str] = {
    "pdf": ".pdf",
    "office-docx": ".docx",
    "office-pptx": ".pptx",
}


def _parse_sync(temp_path: Path, ext: str) -> Any:
    """Synchronous parser dispatch — sniff bytes first, route on result.

    Routing by file extension alone is spoofable: a DOCX renamed
    ``report.pdf`` reaches us as ``ext=".pdf"`` and dies deep inside
    pypdfium2 with an opaque parser error rather than fast at the
    dispatcher with a clear "expected pdf, got office-docx" message.

    This dispatcher sniffs the bytes via
    :func:`kaos_nlp_core.content_type.detect` and routes on the
    detected ``group`` (``"pdf"`` / ``"office-docx"`` /
    ``"office-pptx"``). When kaos-nlp-core is unavailable at runtime
    (the package isn't a hard dependency of kaos-ui itself), we
    gracefully fall back to extension routing with a logged warning so
    pre-existing deployments keep working.

    PDF / DOCX / PPTX return ``ContentDocument`` (kaos-content's AST).
    XLSX is intentionally absent — kaos-office's ``parse_xlsx``
    returns ``TabularDocument``, a different shape; consumers wanting
    tabular uploads should call the tabular pipeline directly.
    """
    # 1. Sniff bytes. Falls back to ext routing if kaos-nlp-core isn't
    #    installed (preserves the kaos-ui-without-NLP-stack baseline).
    detected_group: str | None = None
    detected_mime: str = ""
    try:
        from kaos_nlp_core.content_type import detect  # ty: ignore[unresolved-import]

        result = detect(temp_path.read_bytes())
        detected_group = result.group
        detected_mime = result.mime_type
    except ImportError:
        logger.warning(
            "kaos_nlp_core.content_type unavailable; falling back to extension-based "
            "routing for upload (ext=%s). Install `kaos-nlp-core>=0.1.1` to enable "
            "spoof-resistant byte sniffing.",
            ext,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "content-type detection raised %s; falling back to extension routing (ext=%s)",
            exc,
            ext,
        )

    # 2. Bytes-based dispatch when detection succeeded with a known group.
    if detected_group in _BYTES_GROUP_TO_EXT:
        expected_ext = _BYTES_GROUP_TO_EXT[detected_group]
        if ext != expected_ext:
            logger.debug(
                "upload ext/bytes mismatch resolved by bytes: declared_ext=%r "
                "expected_ext=%r detected_group=%r mime=%r",
                ext,
                expected_ext,
                detected_group,
                detected_mime,
            )
        if detected_group == "pdf":
            from kaos_pdf import extract_pdf  # ty: ignore[unresolved-import]

            return extract_pdf(temp_path)
        if detected_group == "office-docx":
            from kaos_office import parse_docx  # ty: ignore[unresolved-import]

            return parse_docx(temp_path)
        if detected_group == "office-pptx":
            from kaos_office import parse_pptx  # ty: ignore[unresolved-import]

            return parse_pptx(temp_path)

    # 3. Detection ran but found nothing supported → refuse with a clear,
    #    actionable error rather than fall through to a parser that will
    #    crash deep in a third-party library. Uploads are user-facing;
    #    fail fast (audit §8 Q2, option b).
    if detected_group is not None and detected_group not in _BYTES_GROUP_TO_EXT:
        if detected_group == "unknown":
            raise UploadValidationError(
                what=(
                    f"could not identify content type for upload "
                    f"(declared ext={ext!r}, no recognizable magic-byte signature)"
                ),
                how_to_fix="upload a PDF, DOCX, or PPTX file",
            )
        raise UploadValidationError(
            what=(
                f"unsupported content type {detected_mime or detected_group!r} "
                f"(detected group={detected_group!r}, declared ext={ext!r})"
            ),
            how_to_fix="upload one of: .pdf, .docx, .pptx",
        )

    # 4. Detection unavailable → extension fallback (legacy path).
    if ext == ".pdf":
        from kaos_pdf import extract_pdf  # ty: ignore[unresolved-import]

        return extract_pdf(temp_path)
    if ext == ".docx":
        from kaos_office import parse_docx  # ty: ignore[unresolved-import]

        return parse_docx(temp_path)
    if ext == ".pptx":
        from kaos_office import parse_pptx  # ty: ignore[unresolved-import]

        return parse_pptx(temp_path)
    raise UploadValidationError(
        what=f"unsupported file extension {ext!r}",
        how_to_fix="upload one of: .pdf, .docx, .pptx",
    )


async def _parse_offloaded(temp_path: Path, ext: str) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_PARSER_EXECUTOR, _parse_sync, temp_path, ext)


async def _enrich_parsed_doc(
    *,
    parsed_doc: Any,
    session_id: str,
    filename: str,
    summarizer_model: str | None,
    summary_input_cap_chars: int,
) -> tuple[int | None, str | None]:
    """Compute token count + a 2-3 sentence summary for a parsed document.

    Both are best-effort. Tokenizer failures or LLM outages leave the
    corresponding field null; the upload still succeeds.
    """
    try:
        from kaos_content import serialize_markdown  # ty: ignore[unresolved-import]

        text = serialize_markdown(parsed_doc)
    except Exception as exc:
        logger.warning(
            "serialize_markdown failed for session=%s file=%s: %s",
            session_id,
            filename,
            exc,
            extra={"session_id": session_id, "upload_filename": filename},
        )
        return None, None

    token_count: int | None = None
    try:
        from kaos_nlp_core.tokenizer import Tokenizer  # ty: ignore[unresolved-import]

        token_count = len(Tokenizer().tokenize(text))
    except Exception as exc:
        logger.warning(
            "tokenize failed for session=%s file=%s: %s",
            session_id,
            filename,
            exc,
            extra={"session_id": session_id, "upload_filename": filename},
        )

    summary: str | None = None
    if summarizer_model is not None:
        try:
            from kaos_llm_core.starter import summarize  # ty: ignore[unresolved-import]

            body = text if len(text) <= summary_input_cap_chars else text[:summary_input_cap_chars]
            if len(text) > summary_input_cap_chars:
                logger.debug(
                    "summary input truncated session=%s file=%s len=%d cap=%d",
                    session_id,
                    filename,
                    len(text),
                    summary_input_cap_chars,
                    extra={"session_id": session_id, "upload_filename": filename},
                )
            summary = await summarize(body, model=summarizer_model, max_words=120, style="concise")
        except Exception as exc:
            logger.warning(
                "summarize failed for session=%s file=%s: %s",
                session_id,
                filename,
                exc,
                extra={"session_id": session_id, "upload_filename": filename},
            )

    return token_count, summary


def _serialize_doc(doc: Any) -> bytes:
    if hasattr(doc, "model_dump_json"):
        return doc.model_dump_json().encode("utf-8")
    raise UploadParseError(
        what="parsed document does not expose model_dump_json()",
        how_to_fix="parser API drift — file an issue against kaos-content",
    )


# ── public API ───────────────────────────────────────────────────────


async def store_and_parse(
    *,
    runtime: KaosRuntime,
    session_id: str,
    raw_filename: str,
    data: bytes,
    content_type: str | None = None,
    supported_extensions: tuple[str, ...] = (".pdf", ".docx", ".pptx"),
    summarizer_model: str | None = None,
    summary_input_cap_chars: int = 10_000,
) -> FileMeta:
    """Persist + parse one uploaded file. Caller validates size before
    handing us the bytes (route is the place to surface a 413).

    Returns the :class:`FileMeta` describing the saved file and the
    parse outcome. Even when parsing fails, the original bytes are
    persisted — that's the contract.

    ``summarizer_model`` is opt-in: pass a provider:model string to
    have :func:`kaos_llm_core.starter.summarize` produce a 2-3 sentence
    summary on the parsed AST. Pass None to skip the LLM call.
    """
    filename = _safe_filename(raw_filename)
    ext = Path(filename).suffix.lower()
    if ext not in supported_extensions:
        raise UploadValidationError(
            what=f"unsupported file extension {ext!r}",
            how_to_fix=f"upload one of: {', '.join(supported_extensions)}",
        )

    vfs_path = _vfs_path(session_id, filename)
    vfs = runtime.vfs

    await vfs.write(vfs_path, data)

    parse_status: FileParseStatus
    parsed_doc: Any | None = None
    with NamedTemporaryFile(prefix="kaos-upload-", suffix=ext, delete=False) as tf:
        temp_path = Path(tf.name)
        tf.write(data)
    try:
        parsed_doc = await _parse_offloaded(temp_path, ext)
        parse_status = FileParseStatus(status="ready")
    except UploadValidationError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        logger.warning(
            "parse failed for session=%s file=%s ext=%s: %s",
            session_id,
            filename,
            ext,
            exc,
            extra={"session_id": session_id, "upload_filename": filename},
        )
        parse_status = FileParseStatus(status="failed", error=str(exc)[:500])
    finally:
        temp_path.unlink(missing_ok=True)

    token_count: int | None = None
    summary: str | None = None
    if parsed_doc is not None and parse_status.status == "ready":
        ast_bytes = _serialize_doc(parsed_doc)
        await vfs.write(f"{vfs_path}.kaos.json", ast_bytes)
        token_count, summary = await _enrich_parsed_doc(
            parsed_doc=parsed_doc,
            session_id=session_id,
            filename=filename,
            summarizer_model=summarizer_model,
            summary_input_cap_chars=summary_input_cap_chars,
        )

    meta = FileMeta(
        filename=filename,
        size_bytes=len(data),
        content_type=content_type,
        uploaded_at=datetime.now(UTC),
        parse=parse_status,
        token_count=token_count,
        summary=summary,
    )
    await vfs.write(f"{vfs_path}.meta.json", meta.model_dump_json().encode("utf-8"))
    if parse_status.status == "ready":
        logger.debug(
            "upload+parse ok session=%s file=%s size=%d",
            session_id,
            filename,
            len(data),
            extra={"session_id": session_id, "upload_filename": filename},
        )
    return meta


async def list_session_files(*, runtime: KaosRuntime, session_id: str) -> list[FileMeta]:
    """Return :class:`FileMeta` for every uploaded file in a session.

    Walks ``sessions/{id}/files/`` and reads each ``*.meta.json``.
    Skips meta sidecars that fail to validate so a single corrupt
    record doesn't 500 the list endpoint.
    """
    prefix = f"sessions/{session_id}/files/"
    paths = await runtime.vfs.list(prefix)
    out: list[FileMeta] = []
    for path in sorted(paths):
        if not path.endswith(".meta.json"):
            continue
        try:
            raw = await runtime.vfs.read(path)
            out.append(FileMeta.model_validate_json(raw))
        except Exception as exc:
            logger.warning(
                "skipping unreadable meta sidecar path=%s: %s",
                path,
                exc,
                extra={"session_id": session_id, "meta_path": path},
            )
    return out


async def read_session_file(
    *, runtime: KaosRuntime, session_id: str, filename: str
) -> tuple[bytes, FileMeta]:
    """Return ``(bytes, meta)`` for one uploaded file.

    Raises :class:`UploadFileNotFoundError` when the meta sidecar is
    absent — the delete helper uses the same signal so 404 semantics
    are consistent.
    """
    safe = _safe_filename(filename)
    base = _vfs_path(session_id, safe)
    meta_path = f"{base}.meta.json"
    if not await runtime.vfs.exists(meta_path):
        raise UploadFileNotFoundError(
            what=f"no file {filename!r} in session {session_id}",
            how_to_fix="check list_session_files() for valid names",
        )
    meta = FileMeta.model_validate_json(await runtime.vfs.read(meta_path))
    if not await runtime.vfs.exists(base):
        raise UploadFileNotFoundError(
            what=f"file {filename!r} exists in metadata but bytes are missing",
            how_to_fix="re-upload the file or DELETE then re-upload",
        )
    data = await runtime.vfs.read(base)
    return data, meta


async def delete_session_file(*, runtime: KaosRuntime, session_id: str, filename: str) -> None:
    """Remove the original bytes + ``.kaos.json`` + ``.meta.json``.

    Raises :class:`UploadFileNotFoundError` if the meta sidecar is
    absent. AST sibling is removed best-effort (missing AST is normal
    when the parse failed).
    """
    safe = _safe_filename(filename)
    base = _vfs_path(session_id, safe)
    meta_path = f"{base}.meta.json"
    if not await runtime.vfs.exists(meta_path):
        raise UploadFileNotFoundError(
            what=f"no file {filename!r} in session {session_id}",
            how_to_fix="check list_session_files() for valid names",
        )
    for path in (base, f"{base}.kaos.json"):
        if await runtime.vfs.exists(path):
            await runtime.vfs.delete(path)
    await runtime.vfs.delete(meta_path)
    logger.debug(
        "deleted upload session=%s file=%s",
        session_id,
        safe,
        extra={"session_id": session_id, "upload_filename": safe},
    )


async def render_session_corpus_markdown(
    *,
    runtime: KaosRuntime,
    session_id: str,
    per_file_budget_chars: int = 40_000,
) -> str:
    """Build a single markdown block summarizing every ready-parsed
    file in the session, suitable for inlining into the agent's
    system prompt.

    Each file contributes up to ``per_file_budget_chars`` characters
    of its serialized-markdown rendering. Files with a failed parse
    are listed by name + size only. Returns an empty string when no
    files exist.

    The per-file header includes both VFS paths (raw bytes and
    parsed-AST) so the agent knows the exact path argument for
    ``kaos-core-vfs-read``, ``kaos-pdf-*``, and ``kaos-content-*``
    tools. Files larger than the budget get a truncation note + a
    pointer at the search tools so the agent uses them rather than
    guessing about content past the head.
    """
    metas = await list_session_files(runtime=runtime, session_id=session_id)
    if not metas:
        return ""

    try:
        from kaos_content import (  # ty: ignore[unresolved-import]
            ContentDocument,
            serialize_markdown,
        )
    except ImportError:
        logger.warning("kaos_content not importable; skipping corpus rendering")
        return ""

    chunks: list[str] = []
    for meta in metas:
        vfs_path = _vfs_path(session_id, meta.filename)
        ast_path = f"{vfs_path}.kaos.json"

        header_lines = [
            f"### {meta.filename}",
            f"- size: {meta.size_bytes} bytes"
            + (f" · ~{meta.token_count} tokens" if meta.token_count else ""),
            f"- content_type: {meta.content_type or 'unknown'}",
            f"- VFS bytes: `{vfs_path}`",
            f"- VFS AST (kaos-content): `{ast_path}`",
        ]
        if meta.parse.status != "ready":
            header_lines.append(
                f"- parse: FAILED ({meta.parse.error or 'unknown'}) — "
                "raw bytes still readable via `kaos-core-vfs-read` at the VFS bytes path above."
            )
            chunks.append("\n".join(header_lines))
            continue
        header_lines.append("- parse: READY")

        try:
            ast_bytes = await runtime.vfs.read(ast_path)
            doc = ContentDocument.model_validate_json(ast_bytes)
            body = serialize_markdown(doc)
        except Exception as exc:
            logger.warning(
                "could not render AST for %s: %s",
                meta.filename,
                exc,
                extra={"session_id": session_id, "upload_filename": meta.filename},
            )
            chunks.append("\n".join([*header_lines, "_(AST sidecar unreadable)_"]))
            continue

        truncated = len(body) > per_file_budget_chars
        if truncated:
            body = body[:per_file_budget_chars] + "\n\n...[head excerpt — more available via tools]"
            logger.debug(
                "corpus inline truncated session=%s file=%s len=%d budget=%d",
                session_id,
                meta.filename,
                len(body),
                per_file_budget_chars,
                extra={"session_id": session_id, "upload_filename": meta.filename},
            )
            header_lines.append(
                "- WARNING: only the first "
                f"{per_file_budget_chars // 1000}k chars are inlined below. For the rest, "
                "call `kaos-content-search-document` (path = the AST path above) "
                "or `kaos-pdf-extract-page-text` (path = the bytes path above)."
            )

        chunks.append("\n".join(header_lines) + "\n\n" + body)

    return "\n\n---\n\n".join(chunks)


async def backfill_session_files(
    *,
    runtime: KaosRuntime,
    session_id: str,
    summarizer_model: str | None = None,
    summary_input_cap_chars: int = 10_000,
    overwrite: bool = False,
    filename: str | None = None,
) -> int:
    """Recompute token_count + summary for ready-parsed files that
    are missing them.

    Reads each ``.kaos.json`` AST sidecar (skipping failed parses),
    runs the enrichment, and rewrites the ``.meta.json`` sidecar
    with the new fields. Returns the count of files updated.

    ``overwrite=False`` skips files that already have both fields.
    Pass ``True`` to force-refresh (eg. after a summarizer prompt
    change). Pass ``filename`` to scope to a single file.
    """
    try:
        from kaos_content import ContentDocument  # ty: ignore[unresolved-import]
    except ImportError:
        logger.warning("kaos_content not importable; cannot backfill")
        return 0

    prefix = f"sessions/{session_id}/files/"
    paths = sorted(await runtime.vfs.list(prefix))
    meta_paths = [p for p in paths if p.endswith(".meta.json")]
    updated = 0
    for meta_path in meta_paths:
        try:
            raw = await runtime.vfs.read(meta_path)
            meta = FileMeta.model_validate_json(raw)
        except Exception:
            continue
        if filename is not None and meta.filename != filename:
            continue
        if meta.parse.status != "ready":
            continue
        if not overwrite and meta.token_count is not None and meta.summary is not None:
            continue
        ast_path = meta_path[: -len(".meta.json")] + ".kaos.json"
        try:
            ast_raw = await runtime.vfs.read(ast_path)
            doc = ContentDocument.model_validate_json(ast_raw)
        except Exception as exc:
            logger.warning(
                "backfill: AST read failed for %s: %s",
                ast_path,
                exc,
                extra={"session_id": session_id, "meta_path": meta_path},
            )
            continue
        token_count, summary = await _enrich_parsed_doc(
            parsed_doc=doc,
            session_id=session_id,
            filename=meta.filename,
            summarizer_model=summarizer_model,
            summary_input_cap_chars=summary_input_cap_chars,
        )
        new_meta = meta.model_copy(update={"token_count": token_count, "summary": summary})
        await runtime.vfs.write(meta_path, new_meta.model_dump_json().encode("utf-8"))
        updated += 1
    return updated


def _ensure_quiet_thirdparty_logging() -> None:
    """Quiet noisy parser logs. Idempotent; safe to call at import."""
    for name in ("pypdfium2", "pdfminer", "openpyxl"):
        logging.getLogger(name).setLevel(logging.WARNING)


_ensure_quiet_thirdparty_logging()


__all__ = [
    "FileMeta",
    "FileParseStatus",
    "backfill_session_files",
    "delete_session_file",
    "list_session_files",
    "read_session_file",
    "render_session_corpus_markdown",
    "store_and_parse",
]
