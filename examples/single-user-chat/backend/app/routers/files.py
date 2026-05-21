"""/v1/chat/sessions/{session_id}/files — upload + parse.

P1-1 of the upload pipeline. Owns the route surface; the heavy lifting
(filename sanitization, parser dispatch, VFS persistence, parse-status
sidecar) lives in ``app.services.uploads``.

Per-session contract:
- Uploads land in the runtime VFS at ``sessions/{id}/files/{name}``.
- A ``.kaos.json`` sibling holds the parsed ``ContentDocument`` AST.
- A ``.meta.json`` sibling holds the per-file metadata + parse status.
- The session's ``tools_enabled`` flag is auto-flipped to True so the
  agent can use the read-only tool surface against the uploaded
  content on the next turn (RAG-by-default per the v2 plan).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from kaos_core import KaosRuntime

from app.auth import require_auth
from app.deps import get_runtime, get_session_store, get_settings
from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import CorpusSearchHitWire, CorpusSearchResponse, FileListResponse, UploadResponse
from app.persistence.sessions import SessionStore
from app.services.uploads import (
    FileNotFoundError,
    UploadParseError,
    UploadValidationError,
    backfill_session_files,
    delete_session_file,
    list_session_files,
    read_session_file,
    store_and_parse,
)
from app.settings import AppSettings

router = APIRouter(tags=["files"])
logger = app_logger("files_router")

SettingsDep = Annotated[AppSettings, Depends(get_settings)]
StoreDep = Annotated[SessionStore, Depends(get_session_store)]
RuntimeDep = Annotated[KaosRuntime, Depends(get_runtime)]
# R0.2: capture the tenant id from ``require_auth`` per-route so we can
# thread it into the uploads pipeline. The router-level
# ``dependencies=[Depends(require_auth)]`` only gated the call without
# yielding the tenant id; switching to a per-handler ``Annotated``
# dependency keeps the gate AND lets the handler scope the VFS path.
TenantDep = Annotated[str | None, Depends(require_auth)]


def _validation_detail(exc: UploadValidationError | UploadParseError) -> dict[str, str]:
    detail = {"what": exc.what, "how_to_fix": exc.how_to_fix}
    if exc.alternative:
        detail["alternative"] = exc.alternative
    return detail


@router.post(
    "/sessions/{session_id}/files",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    session_id: str,
    file: Annotated[UploadFile, File(description="Upload .pdf / .docx / .pptx")],
    settings: SettingsDep,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
) -> UploadResponse:
    """Accept one file, persist + parse, auto-flip tools_enabled."""
    try:
        meta = await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # 413 fast-path: trust the Content-Length the upstream proxy
    # delivered, when present. Caddy / nginx set this from the
    # multipart body it parses, so we reject obviously-too-large
    # uploads before ever touching the body.
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "what": (f"upload is {file.size} bytes, max is {settings.max_upload_bytes}"),
                "how_to_fix": (
                    "split the file or compress it; "
                    f"max upload size is {settings.max_upload_bytes // (1024 * 1024)} MiB"
                ),
            },
        )

    # FIX-11: stream-read in chunks so a body without a trustworthy
    # Content-Length (or one that lies) can't OOM the process. We
    # bail at the FIRST chunk that pushes us past the cap — the
    # cumulative buffer is bounded at `max_upload_bytes + chunk`.
    _UPLOAD_CHUNK_BYTES = 64 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            # Drop accumulated chunks + close the upload tempfile.
            chunks.clear()
            await file.close()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "what": (f"upload exceeded {settings.max_upload_bytes} bytes while streaming"),
                    "how_to_fix": (
                        "split the file or compress it; "
                        f"max upload size is {settings.max_upload_bytes // (1024 * 1024)} MiB"
                    ),
                },
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    try:
        file_meta = await store_and_parse(
            runtime=runtime,
            session_id=session_id,
            raw_filename=file.filename or "upload",
            data=data,
            content_type=file.content_type,
            supported_extensions=settings.supported_upload_extensions,
            tenant_id=tenant_id,
        )
    except UploadValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=_validation_detail(exc),
        ) from exc
    except UploadParseError as exc:
        logger.warning(
            "parser failed for session=%s file=%s",
            session_id,
            file.filename,
            extra={"session_id": session_id, "upload_filename": file.filename},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_validation_detail(exc),
        ) from exc

    if not meta.tools_enabled:
        meta = await store.patch(session_id, tools_enabled=True, tenant_id=tenant_id)
        logger.info(
            "auto-flipped tools_enabled=True for session=%s after upload",
            session_id,
            extra={"session_id": session_id, "upload_filename": file_meta.filename},
        )

    return UploadResponse(
        session_id=session_id,
        file=file_meta,
        tools_enabled=meta.tools_enabled,
    )


@router.get(
    "/sessions/{session_id}/files/search",
    response_model=CorpusSearchResponse,
)
async def search_corpus(
    session_id: str,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
    q: str,
    top_k: int = 10,
) -> CorpusSearchResponse:
    """P2-3 — BM25 search over the session's ready-parsed uploads.

    Returns paragraph-level hits ordered by descending score. The
    SPA can render hits as "jump to source" affordances; the agent
    can also call this surface via a future `kaos-content-*` tool
    bridged on the runtime.
    """
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    from app.services.corpus_search import search_session_corpus

    hits = await search_session_corpus(
        runtime=runtime,
        session_id=session_id,
        query=q,
        top_k=max(1, min(top_k, 50)),
        tenant_id=tenant_id,
    )
    return CorpusSearchResponse(
        session_id=session_id,
        query=q,
        count=len(hits),
        hits=[
            CorpusSearchHitWire(
                filename=h.filename,
                score=h.score,
                snippet=h.snippet,
                char_offset=h.char_offset,
            )
            for h in hits
        ],
    )


@router.get(
    "/sessions/{session_id}/files",
    response_model=FileListResponse,
)
async def list_files(
    session_id: str,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
) -> FileListResponse:
    """Return every uploaded file for this session, with parse status."""
    # Validate the session exists; if not, this is a 404, not an empty list
    # — the SPA needs to distinguish "session has no files" from "session
    # never existed."
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    files = await list_session_files(
        runtime=runtime, session_id=session_id, tenant_id=tenant_id
    )
    return FileListResponse(session_id=session_id, files=files)


@router.post("/sessions/{session_id}/files:backfill")
async def backfill_files(
    session_id: str,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
    overwrite: bool = False,
    filename: str | None = None,
) -> dict[str, int]:
    """Recompute token_count + summary for files missing them.

    Useful after a backend upgrade that adds new sidecar fields, or
    after the summarizer was offline at upload time. Pass
    ``?overwrite=true`` to refresh every file regardless. Pass
    ``?filename=`` to scope to a single file (the per-file
    Re-summarize action in DocumentExplorer uses this).
    """
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    updated = await backfill_session_files(
        runtime=runtime,
        session_id=session_id,
        overwrite=overwrite,
        filename=filename,
        tenant_id=tenant_id,
    )
    return {"updated": updated}


@router.get(
    "/sessions/{session_id}/files/{filename:path}/download",
    response_class=Response,
)
async def download_file(
    session_id: str,
    filename: str,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
) -> Response:
    """Stream the original bytes of an uploaded file back to the caller.

    The `Content-Type` matches what the user uploaded (per-file
    `meta.content_type`); the `Content-Disposition` is `attachment`
    so the browser saves rather than opens the file inline.
    """
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        data, meta = await read_session_file(
            runtime=runtime,
            session_id=session_id,
            filename=filename,
            tenant_id=tenant_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"what": exc.what, "how_to_fix": exc.how_to_fix},
        ) from exc

    # RFC 6266: quote any special chars in the filename header.
    safe_attachment = meta.filename.replace('"', '\\"')
    return Response(
        content=data,
        media_type=meta.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_attachment}"',
            "Content-Length": str(len(data)),
        },
    )


@router.delete(
    "/sessions/{session_id}/files/{filename:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(
    session_id: str,
    filename: str,
    store: StoreDep,
    runtime: RuntimeDep,
    tenant_id: TenantDep,
) -> None:
    """Remove an uploaded file (bytes + AST sidecar + meta sidecar)."""
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        await delete_session_file(
            runtime=runtime,
            session_id=session_id,
            filename=filename,
            tenant_id=tenant_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"what": exc.what, "how_to_fix": exc.how_to_fix},
        ) from exc
