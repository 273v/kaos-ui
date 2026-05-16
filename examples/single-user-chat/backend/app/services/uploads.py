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


def _resolve_summarizer_model() -> str:
    """Read the summarizer model from AppSettings at call time so
    `APP_SUMMARIZER_MODEL` env-var overrides take effect per request.
    """
    from app.settings import AppSettings

    return AppSettings().summarizer_model


def _resolve_summary_input_cap() -> int:
    """Soft char-cap on summarizer input — chosen to fit comfortably
    inside the configured model's context with headroom for the
    instruction template. 800k chars ≈ 200k tokens, safely under
    Haiku 4.5 / Sonnet 4.6's context windows. Override via
    `APP_SUMMARY_INPUT_CAP` for million-token long contexts.

    DOES NOT silently summarize a head-excerpt anymore — pre-this
    change we capped at 12k chars, which was wrong for legal use
    where a single SEC filing or deal-room PDF easily exceeds 100k
    tokens. The cap is now only a runaway-cost guard.
    """
    from app.settings import AppSettings

    return AppSettings().summary_input_cap_chars


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

        cap = _resolve_summary_input_cap()
        body = text if len(text) <= cap else text[:cap]
        if len(text) > cap:
            logger.info(
                "summary input truncated session=%s file=%s len=%d cap=%d",
                session_id,
                filename,
                len(text),
                cap,
                extra={"session_id": session_id, "upload_filename": filename},
            )
        summary = await summarize(
            body,
            model=_resolve_summarizer_model(),
            max_words=120,
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
    filename: str | None = None,
) -> int:
    """Recompute token_count + summary for ready-parsed files that are
    missing them.

    Reads each `.kaos.json` AST sidecar (skipping files whose parse
    failed), runs `_enrich_parsed_doc`, and rewrites the `.meta.json`
    sidecar with the new fields. Returns the count of files updated.

    `overwrite=False` is the default — files that already have BOTH a
    token_count and a summary are skipped. Pass `True` to refresh
    everything (useful after a summarizer prompt change). Pass a
    `filename` to scope the operation to a single file (used by the
    per-file Re-summarize action in DocumentExplorer).
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
        if filename is not None and meta.filename != filename:
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


# Per-file inline budget for the chat-context corpus. Sized for Haiku
# 4.5's 200k-token window: we reserve ~30k tokens for the prompt +
# response headroom, leaving ~170k tokens (~680k chars) for the corpus.
# With a typical legal upload mix (≤ 20 files), 40k chars/file gives
# the agent enough of each document to actually answer "what does this
# say about Georgia?" — the prior 4k cap was barely a single page and
# was the reason the agent kept apologizing about "truncated previews".
#
# Override via `APP_PER_FILE_PROMPT_BUDGET_CHARS`. For Sonnet 4.6 (1M
# context) you can safely 5x this. Logged-truncation events tell ops
# when a single file exceeds the budget so they can tune.
_PER_FILE_PROMPT_BUDGET = 40_000


def _resolve_per_file_prompt_budget() -> int:
    """Read the per-file inline budget from AppSettings at call time so
    `APP_PER_FILE_PROMPT_BUDGET_CHARS` env overrides take effect without
    a process restart.
    """
    from app.settings import AppSettings

    return AppSettings().per_file_prompt_budget_chars


async def render_session_corpus_markdown(
    *,
    runtime: KaosRuntime,
    session_id: str,
    per_file_budget_chars: int | None = None,  # kept for back-compat — no longer used
) -> str:
    """Render a metadata-only catalog of every file attached to the session.

    **No file body is inlined.** Each file contributes a few lines:
    filename, size, content type, the two VFS path arguments the
    agent will use to read it (`bytes` for PDF/Office tools, `AST`
    for kaos-content tools), parse status, and the cached one-line
    summary (computed at upload time by ``maybe_compute_summary``).

    This mirrors kelvin-agent's `Document.to_compact_dict()` pattern
    — the model sees enough to decide which file is relevant and
    which tool to call, but the actual content stays out of the
    prompt and is fetched on demand. For 1 KB of metadata per file,
    we can list ~50 files in the prompt; the agent searches via
    `kaos-content-corpus-narrow` / `kaos-content-search-document` /
    `kaos-pdf-extract-page-text` for the rest.

    Pre-2026-05-16 this function inlined `serialize_markdown(doc)`
    up to a 40,000-char-per-file budget. A 20-file legal upload mix
    pushed ~200K tokens of inert document body into every turn —
    including replan iterations — even when the agent didn't read
    any of them. The thin-worker-prompt refactor
    (kaos-modules/docs/plans/thin-worker-prompt.md) deletes that
    inlining path.

    The ``per_file_budget_chars`` parameter is retained as a kwarg
    for back-compat with callers that pass it; it is no longer used
    because no body content is inlined.
    """
    metas = await list_session_files(runtime=runtime, session_id=session_id)
    if not metas:
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
            f"- VFS AST: `{ast_path}`",
        ]
        if meta.parse.status != "ready":
            header_lines.append(
                f"- parse: FAILED ({meta.parse.error or 'unknown'}) — "
                "raw bytes still readable via `kaos-core-vfs-read` at the "
                "VFS bytes path above."
            )
            chunks.append("\n".join(header_lines))
            continue
        header_lines.append("- parse: READY")
        if meta.summary:
            header_lines.append(f"- summary: {meta.summary}")

        chunks.append("\n".join(header_lines))

    return "\n\n".join(chunks)


class FileNotFoundError(UploadError):
    """No such file in the session's VFS prefix."""


async def read_session_file(
    *, runtime: KaosRuntime, session_id: str, filename: str
) -> tuple[bytes, FileMeta]:
    """Return (original_bytes, meta) for one uploaded file.

    Raises FileNotFoundError when the meta sidecar is absent — the
    delete route uses the same signal so 404 semantics are consistent.
    """
    safe = _safe_filename(filename)
    base = _vfs_path(session_id, safe)
    meta_path = f"{base}.meta.json"
    if not await runtime.vfs.exists(meta_path):
        raise FileNotFoundError(
            what=f"no file {filename!r} in session {session_id}",
            how_to_fix="check GET /v1/chat/sessions/{id}/files for valid names",
        )
    meta = FileMeta.model_validate_json(await runtime.vfs.read(meta_path))
    if not await runtime.vfs.exists(base):
        raise FileNotFoundError(
            what=f"file {filename!r} exists in metadata but bytes are missing",
            how_to_fix="re-upload the file or DELETE then re-upload",
        )
    data = await runtime.vfs.read(base)
    return data, meta


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
