"""/v1/chat/* — sidecar metadata + SSE proxy.

Routes:
  POST   /v1/chat/sessions               create session (+ upstream POST /v1/sessions)
  GET    /v1/chat/sessions               list session metadata
  GET    /v1/chat/sessions/{id}/meta     read one session's metadata
  PATCH  /v1/chat/sessions/{id}/meta     update metadata
  POST   /v1/chat/sessions/{id}/archive  archive (soft delete)
  POST   /v1/chat/sessions/{id}/messages SSE proxy to kaos-agents
  GET    /v1/chat/sessions/{id}/transcript  Phase 3
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette import EventSourceResponse

from app.deps import get_session_store, get_settings, get_upstream_client
from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import (
    ArchiveResponse,
    CreateSessionBody,
    PatchMetaBody,
    SendMessageBody,
    SessionListResponse,
    SessionMeta,
)
from app.persistence.sessions import SessionStore
from app.services.stream_proxy import _bearer_from_env, stream_chat
from app.settings import AppSettings

router = APIRouter(tags=["chat"])
logger = app_logger("chat_router")


SettingsDep = Annotated[AppSettings, Depends(get_settings)]
StoreDep = Annotated[SessionStore, Depends(get_session_store)]
UpstreamDep = Annotated[httpx.AsyncClient, Depends(get_upstream_client)]


def _bearer_from_request(request: Request) -> str:
    """Pull the inbound bearer for forwarding to the kaos-agents API."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    # Fallback to the env-configured token (same process, same token).
    return _bearer_from_env()


async def _upstream_create_session(
    *, client: httpx.AsyncClient, bearer: str, session_id: str
) -> None:
    """Register the session id with kaos-agents so its namespace exists."""
    r = await client.post(
        "/v1/sessions",
        headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
        json={"session_id": session_id},
    )
    if r.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Upstream kaos-agents POST /v1/sessions returned {r.status_code}. "
                f"Body: {r.text[:300]}"
            ),
        )


# ── routes ──────────────────────────────────────────────────────────


@router.post("/sessions", response_model=SessionMeta, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionBody,
    request: Request,
    settings: SettingsDep,
    store: StoreDep,
    upstream: UpstreamDep,
) -> SessionMeta:
    """Create a new chat session.

    Two-step: (1) POST /v1/sessions upstream so kaos-agents reserves
    the namespace, (2) write our metadata sidecar.
    """
    from app.persistence.sessions import new_session_id

    sid = new_session_id()
    bearer = _bearer_from_request(request)
    await _upstream_create_session(client=upstream, bearer=bearer, session_id=sid)
    meta = await store.create(
        session_id=sid,
        title=body.title or "Untitled",
        model=body.model or settings.default_model,
        system_prompt=body.system_prompt or settings.default_system_prompt,
        tools_enabled=body.tools_enabled
        if body.tools_enabled is not None
        else settings.default_tools_enabled,
    )
    logger.info("created session %s", sid)
    return meta


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    store: StoreDep,
    limit: int = 50,
    cursor: str | None = None,
    archived: bool = False,
) -> SessionListResponse:
    summaries, next_cursor = await store.list(limit=limit, cursor=cursor, archived=archived)
    return SessionListResponse(sessions=summaries, next_cursor=next_cursor)


@router.get("/sessions/{session_id}/meta", response_model=SessionMeta)
async def get_meta(session_id: str, store: StoreDep) -> SessionMeta:
    try:
        return await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}/meta", response_model=SessionMeta)
async def patch_meta(session_id: str, body: PatchMetaBody, store: StoreDep) -> SessionMeta:
    try:
        return await store.patch(
            session_id,
            title=body.title,
            model=body.model,
            system_prompt=body.system_prompt,
            tools_enabled=body.tools_enabled,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/archive", response_model=ArchiveResponse)
async def archive_session(session_id: str, store: StoreDep) -> ArchiveResponse:
    try:
        archived_at = await store.archive(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ArchiveResponse(archived_at=archived_at)


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: SendMessageBody,
    request: Request,
    settings: SettingsDep,
    store: StoreDep,
    upstream: UpstreamDep,
) -> EventSourceResponse:
    """Stream SSE: forward to upstream + bump our metadata on completion."""
    try:
        meta = await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    bearer = _bearer_from_request(request)

    async def event_generator():
        try:
            async for evt in stream_chat(
                client=upstream,
                bearer_token=bearer,
                meta=meta,
                message=body.message,
                max_cost_usd=settings.turn_budget_usd,
            ):
                yield evt
        finally:
            # Bump metadata regardless of stream outcome — partial
            # turns still produced messages.
            try:
                await store.touch(session_id, increment_messages=1)
            except Exception:
                logger.exception("failed to touch session %s after stream", session_id)

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/transcript")
async def transcript_stub(session_id: str) -> dict[str, str]:
    """Phase 3 task #22 will implement Markdown + JSON export."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="transcript export lands in Phase 3",
    )
