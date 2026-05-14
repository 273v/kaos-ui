"""File upload + parse pipeline.

POST /v1/chat/sessions/{id}/files accepts a multipart upload; this
module owns everything that happens after we have ``(filename,
bytes)`` in memory:

1. Persist the original bytes to the runtime VFS at
   ``sessions/{session_id}/files/{filename}`` so the agent's bridged
   tools can read them.
2. Dispatch a parser by extension (PDF / DOCX / PPTX) and parse to a
   ``kaos_content.ContentDocument`` AST.
3. Persist the parsed AST as JSON to a sibling VFS path
   (``.kaos.json``) so we don't re-parse on every retrieval.
4. Persist a per-file metadata sidecar (``.meta.json``) with the
   parse outcome.

The parsers are synchronous and (in the PDF case) not thread-safe at
the PDFium layer. We funnel every parse call through a single-thread
``ThreadPoolExecutor`` so concurrent uploads serialize at the parser
boundary while the rest of the FastAPI request stays async.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from kaos_core import KaosRuntime

from app.exceptions import AppError
from app.logging_setup import app_logger
from app.models import FileMeta, FileParseStatus

logger = app_logger("uploads")

# Single-worker executor. PDFium holds a global C lock; the other
# parsers are sync but happy to be serialized too. Keeps semantics
# predictable across concurrent uploads without a thread pool size
# that varies by host.
_PARSER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload-parser")


class UploadError(AppError):
    """Upload failed in a way the route translates to a 4xx response.

    Carries the kaos-* agent-friendly triple (``what`` / ``how_to_fix`` /
    optional ``alternative``). The message string used by ``AppError``
    is just ``what`` so logs stay scannable; the full triple lives in
    ``self.details`` and surfaces on the wire via the route.
    """

    def __init__(self, *, what: str, how_to_fix: str, alternative: str | None = None) -> None:
        details: dict[str, Any] = {"what": what, "how_to_fix": how_to_fix}
        if alternative is not None:
            details["alternative"] = alternative
        super().__init__(what, **details)
        self.what = what
        self.how_to_fix = how_to_fix
        self.alternative = alternative


class UploadValidationError(UploadError):
    """Caller sent us something we won't accept (size, extension, name)."""


class UploadParseError(UploadError):
    """Bytes saved but the parser refused them."""


# ── filename sanitization ──────────────────────────────────────────


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
            how_to_fix=f"rename the file to ≤ {_MAX_FILENAME_LEN} characters",
        )
    cleaned = "".join(c if c in _ALLOWED_FILENAME_CHARS else "_" for c in base)
    return cleaned


def _vfs_path(session_id: str, filename: str) -> str:
    return f"sessions/{session_id}/files/{filename}"


# ── parser dispatch ────────────────────────────────────────────────


def _parse_sync(temp_path: Path, ext: str) -> Any:
    """Synchronous parser dispatch by extension.

    Returns whatever the parser returns. PDF/DOCX/PPTX return
    ``ContentDocument``; future XLSX support would return
    ``TabularDocument`` (different shape — not enabled in P1).
    """
    if ext == ".pdf":
        # kaos-pdf 0.1.0a2 exports `extract_pdf` (the ContentDocument-
        # returning canonical parser). Newer monorepo HEAD has a
        # `parse_pdf` alias — use the published name for forward-compat
        # against the PyPI release we depend on.
        from kaos_pdf import extract_pdf

        return extract_pdf(temp_path)
    if ext == ".docx":
        from kaos_office import parse_docx

        return parse_docx(temp_path)
    if ext == ".pptx":
        from kaos_office import parse_pptx

        return parse_pptx(temp_path)
    raise UploadValidationError(
        what=f"unsupported file extension {ext!r}",
        how_to_fix="upload one of: .pdf, .docx, .pptx",
    )


async def _parse_offloaded(temp_path: Path, ext: str) -> Any:
    """Run the sync parser inside the single-thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_PARSER_EXECUTOR, _parse_sync, temp_path, ext)


# Soft cap on summarizer input. Haiku's context is huge but anything
# beyond ~12k chars is rarely improved by the marginal tokens — the
# summary picks up document type + key entities + main subject from
# the head + a long tail of repetition. We trim once on the head;
# alternative approaches (chunk + map-reduce) are out of scope for v1.
_SUMMARY_INPUT_CAP = 12_000
_SUMMARY_MODEL = "anthropic:claude-haiku-4-5"


async def _enrich_parsed_doc(
    *,
    parsed_doc: Any,
    session_id: str,
    filename: str,
) -> tuple[int | None, str | None]:
    """Compute token count + a 2-3 sentence summary for a parsed document.

    Both are best-effort. Tokenizer failures or LLM outages leave the
    corresponding field null; the upload still succeeds. The caller
    persists whatever we return into the FileMeta sidecar.

    Why this lives here, not in a separate Program file: the summary
    contract IS the file's meta sidecar shape, so co-locating the
    serializer + tokenizer + LLM call keeps the upload pipeline
    readable as a linear pass.
    """
    # Step 1: serialize the AST to markdown. ContentDocument is the
    # common shape PDF/DOCX/PPTX parsers return.
    try:
        from kaos_content import serialize_markdown

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

    # Step 2: token count via kaos-nlp-core Tokenizer (Unicode-aware,
    # not LLM-specific — gives a stable estimate independent of the
    # current model's BPE).
    token_count: int | None = None
    try:
        from kaos_nlp_core.tokenizer import Tokenizer

        token_count = len(Tokenizer().tokenize(text))
    except Exception as exc:
        logger.warning(
            "tokenize failed for session=%s file=%s: %s",
            session_id,
            filename,
            exc,
            extra={"session_id": session_id, "upload_filename": filename},
        )

    # Step 3: LLM summary via kaos-llm-core.starter.summarize (the
    # canonical Program wrapper). Capped on input length to bound cost;
    # `style="concise"` gives 2-3 sentences focused on type + entities
    # + subject.
    summary: str | None = None
    try:
        from kaos_llm_core.starter import summarize

        head = text[:_SUMMARY_INPUT_CAP]
        summary = await summarize(
            head,
            model=_SUMMARY_MODEL,
            max_words=80,
            style="concise",
        )
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
    """Best-effort JSON serialization of the parsed AST.

    ``ContentDocument`` is a Pydantic v2 model — ``model_dump_json`` is
    the canonical serializer. We don't accept anything else from the
    dispatcher in P1, so a missing method would be a parser-API drift
    we'd want to know about.
    """
    if hasattr(doc, "model_dump_json"):
        return doc.model_dump_json().encode("utf-8")
    raise UploadParseError(
        what="parsed document does not expose model_dump_json()",
        how_to_fix="parser API drift — file an issue against kaos-content",
    )


# ── public entrypoint ──────────────────────────────────────────────


async def store_and_parse(
    *,
    runtime: KaosRuntime,
    session_id: str,
    raw_filename: str,
    data: bytes,
    content_type: str | None = None,
    supported_extensions: tuple[str, ...] = (".pdf", ".docx", ".pptx"),
) -> FileMeta:
    """Persist + parse one uploaded file. Caller validates size before
    handing us the bytes (route is the place to surface a 413 with the
    configured limit).

    Returns the ``FileMeta`` describing the saved file and the parse
    outcome. Even when parsing fails, the original bytes are persisted
    — that's the contract: the user uploaded a file, the file is
    available for direct retrieval (e.g., a future "download my
    upload" feature), only the AST is missing.
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

    # 1. Original bytes → VFS.
    await vfs.write(vfs_path, data)

    # 2. Parse → AST. We need a real filesystem path; the parsers
    # don't read VFS paths. Write to a NamedTemporaryFile, parse, drop.
    # delete=False because the parser may keep a handle open across
    # the with-exit on some platforms; we clean up by hand.
    parse_status: FileParseStatus
    parsed_doc: Any | None = None
    with NamedTemporaryFile(prefix="kaos-upload-", suffix=ext, delete=False) as tf:
        temp_path = Path(tf.name)
        tf.write(data)
    try:
        parsed_doc = await _parse_offloaded(temp_path, ext)
        parse_status = FileParseStatus(status="ready")
    except UploadError:
        # Validation already-typed; re-raise so the route translates it.
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

    # 3. Persist the parsed AST sidecar (only on success).
    token_count: int | None = None
    summary: str | None = None
    if parsed_doc is not None and parse_status.status == "ready":
        ast_bytes = _serialize_doc(parsed_doc)
        await vfs.write(f"{vfs_path}.kaos.json", ast_bytes)
        # Token count + LLM summary are best-effort enrichments.
        # Failures leave them null but never block the upload.
        token_count, summary = await _enrich_parsed_doc(
            parsed_doc=parsed_doc,
            session_id=session_id,
            filename=filename,
        )

    # 4. Per-file metadata sidecar.
    meta = FileMeta(
        filename=filename,
        size_bytes=len(data),
        content_type=content_type,
        uploaded_at=datetime.now(UTC),
        parse=parse_status,
        token_count=token_count,
        summary=summary,
    )
    meta_bytes = meta.model_dump_json().encode("utf-8")
    await vfs.write(f"{vfs_path}.meta.json", meta_bytes)

    if parse_status.status == "ready":
        logger.info(
            "upload+parse ok session=%s file=%s size=%d",
            session_id,
            filename,
            len(data),
            extra={"session_id": session_id, "upload_filename": filename},
        )
    return meta


async def backfill_session_files(
    *,
    runtime: KaosRuntime,
    session_id: str,
    overwrite: bool = False,
) -> int:
    """Recompute token_count + summary for ready-parsed files that are
    missing them.

    Reads each `.kaos.json` AST sidecar (skipping files whose parse
    failed), runs `_enrich_parsed_doc`, and rewrites the `.meta.json`
    sidecar with the new fields. Returns the count of files updated.

    `overwrite=False` is the default — files that already have BOTH a
    token_count and a summary are skipped. Pass `True` to refresh
    everything (useful after a summarizer prompt change).
    """
    from kaos_content import ContentDocument

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
        if meta.parse.status != "ready":
            continue
        if not overwrite and meta.token_count is not None and meta.summary is not None:
            continue
        # AST sidecar path: strip the trailing .meta.json + add .kaos.json.
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
        )
        new_meta = meta.model_copy(update={"token_count": token_count, "summary": summary})
        await runtime.vfs.write(meta_path, new_meta.model_dump_json().encode("utf-8"))
        updated += 1
    return updated


async def list_session_files(*, runtime: KaosRuntime, session_id: str) -> list[FileMeta]:
    """Return the FileMeta for every uploaded file in the session.

    Walks the VFS prefix ``sessions/{id}/files/`` and reads each
    ``*.meta.json`` sidecar. Files whose meta sidecar is missing or
    unreadable are skipped (defensive — old or partially-written
    uploads shouldn't 500 the list endpoint).
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


_PER_FILE_PROMPT_BUDGET = 4000


async def render_session_corpus_markdown(
    *,
    runtime: KaosRuntime,
    session_id: str,
    per_file_budget_chars: int = _PER_FILE_PROMPT_BUDGET,
) -> str:
    """Build a single markdown block summarizing every ready-parsed file
    in the session, suitable for inlining into the agent's system prompt.

    Each file contributes up to ``per_file_budget_chars`` characters of
    its serialized-markdown rendering. Files with a failed parse are
    listed by name + size only. Returns an empty string when no files
    exist.

    This is the P2-2 'RAG-by-default' wire: kaos-agents 0.1.0a1's
    MessageRequest doesn't accept a per-turn ``corpus`` parameter, and
    the bridged kaos-pdf/office tools take filesystem paths (not VFS
    paths), so the cleanest way to make uploads visible to the agent
    is to inline a markdown rendering. A future kaos-agents version
    that accepts corpus= in MessageRequest will let us pass the
    parsed ASTs directly and replace this prompt-side path.
    """
    metas = await list_session_files(runtime=runtime, session_id=session_id)
    if not metas:
        return ""

    try:
        from kaos_content import ContentDocument, serialize_markdown
    except ImportError:
        logger.warning("kaos_content not importable — skipping corpus rendering")
        return ""

    chunks: list[str] = []
    for meta in metas:
        header = f"### {meta.filename} ({meta.size_bytes} bytes"
        if meta.parse.status != "ready":
            header += f", parse FAILED: {meta.parse.error or 'unknown'})"
            chunks.append(header)
            continue
        header += ", parsed)"

        ast_path = f"{_vfs_path(session_id, meta.filename)}.kaos.json"
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
            chunks.append(f"{header}\n_(AST sidecar unreadable)_")
            continue

        if len(body) > per_file_budget_chars:
            body = body[:per_file_budget_chars] + "\n\n…[truncated]"
        chunks.append(f"{header}\n\n{body}")

    return "\n\n---\n\n".join(chunks)


class FileNotFoundError(UploadError):
    """No such file in the session's VFS prefix."""


async def delete_session_file(*, runtime: KaosRuntime, session_id: str, filename: str) -> None:
    """Remove the original bytes + .kaos.json + .meta.json siblings.

    Raises ``FileNotFoundError`` (404 in the route) if the meta
    sidecar is absent — we use that as the canonical "this file
    exists for this session" signal. The original-bytes file and
    the AST sibling are removed best-effort (a missing AST sibling
    is normal when the parse failed).
    """
    safe = _safe_filename(filename)
    base = _vfs_path(session_id, safe)
    meta_path = f"{base}.meta.json"

    if not await runtime.vfs.exists(meta_path):
        raise FileNotFoundError(
            what=f"no file {filename!r} in session {session_id}",
            how_to_fix="check GET /v1/chat/sessions/{id}/files for valid names",
        )

    for path in (base, f"{base}.kaos.json"):
        if await runtime.vfs.exists(path):
            await runtime.vfs.delete(path)
    await runtime.vfs.delete(meta_path)
    logger.info(
        "deleted upload session=%s file=%s",
        session_id,
        safe,
        extra={"session_id": session_id, "upload_filename": safe},
    )


def _ensure_quiet_thirdparty_logging() -> None:
    """Some parsers (pypdfium2, python-pptx) emit verbose info logs.

    Quiet them at INFO level so the structured-log stream stays useful.
    Idempotent; safe to call at import time.
    """
    for name in ("pypdfium2", "pdfminer", "openpyxl"):
        logging.getLogger(name).setLevel(logging.WARNING)


_ensure_quiet_thirdparty_logging()
