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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette import EventSourceResponse

from app.auth import require_auth
from app.deps import get_session_store, get_settings, get_upstream_client
from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import (
    ArchiveResponse,
    CreateSessionBody,
    HistoryMessage,
    HistoryResponse,
    PatchMetaBody,
    SendMessageBody,
    SessionListResponse,
    SessionMeta,
)
from app.persistence.sessions import SessionStore
from app.services.stream_proxy import _bearer_from_env, stream_chat
from app.settings import AppSettings

router = APIRouter(tags=["chat"], dependencies=[Depends(require_auth)])
logger = app_logger("chat_router")


SettingsDep = Annotated[AppSettings, Depends(get_settings)]
StoreDep = Annotated[SessionStore, Depends(get_session_store)]
UpstreamDep = Annotated[httpx.AsyncClient, Depends(get_upstream_client)]


def _bearer_from_request(request: Request) -> str:
    """Forward the inbound bearer to the kaos-agents in-process proxy.

    Auth has already been enforced by `Depends(require_auth)` on the
    router — by the time we get here, the header is present and valid.
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    # Defensive: require_auth should have already 401'd. If we somehow
    # get here without a header, fall back to the env token rather than
    # crash — the upstream call will fail its own auth instead.
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


def _derive_title(first_message: str, *, max_len: int = 60) -> str:
    """Pick a short title from the first user message.

    Strips whitespace, collapses runs, truncates at a word boundary so
    we don't leave dangling characters. Falls back to "Untitled" for
    empty / whitespace-only input.
    """
    text = " ".join(first_message.split())
    if not text:
        return "Untitled"
    if len(text) <= max_len:
        return text
    # Truncate at the last space before max_len so we don't slice a word.
    cutoff = text.rfind(" ", 0, max_len)
    if cutoff <= 0:
        cutoff = max_len
    return text[:cutoff].rstrip() + "…"


def _validate_model_id(model_id: str) -> None:
    """Confirm ``model_id`` is one of the ids in our curated catalog."""
    from app.services.catalog import build_catalog

    valid = {entry.id for entry in build_catalog()}
    if model_id not in valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "what": f"Unknown model id {model_id!r}.",
                "how_to_fix": "Pass one of the ids returned by GET /v1/models.",
                "alternative_tool": "GET /v1/models",
            },
        )


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

    if body.model is not None:
        _validate_model_id(body.model)

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
    limit: int = Query(default=50, ge=1, le=200),
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
    if body.model is not None:
        _validate_model_id(body.model)
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
    runtime = getattr(request.app.state, "kaos_runtime", None)
    available_tool_names: tuple[str, ...]
    if meta.tools_enabled and runtime is not None:
        # Filter the runtime's tool surface by the read-only allowlist
        # before telling the agent about it. The proxy also passes the
        # same allowlist as `tools` so kaos-agents enforces the gate —
        # this catalog is defense-in-depth on the prompt side.
        import fnmatch

        from app.services.catalog import READ_ONLY_TOOL_GLOBS

        all_names = sorted(runtime.tools.list_tools())
        available_tool_names = tuple(
            name
            for name in all_names
            if any(fnmatch.fnmatchcase(name, glob) for glob in READ_ONLY_TOOL_GLOBS)
        )
    else:
        available_tool_names = ()

    # First turn auto-derives a title from the user message so the
    # sidebar isn't a sea of "Untitled".
    is_first_turn = meta.message_count == 0 and meta.title == "Untitled"

    async def event_generator():
        try:
            async for evt in stream_chat(
                client=upstream,
                bearer_token=bearer,
                meta=meta,
                message=body.message,
                max_cost_usd=settings.turn_budget_usd,
                available_tool_names=available_tool_names,
            ):
                yield evt
        finally:
            # Increment by 1: a turn is (user message + assistant reply),
            # not two messages. Set title on first turn from the user
            # input, truncated at word boundary.
            try:
                if is_first_turn:
                    await store.patch(session_id, title=_derive_title(body.message))
                await store.touch(session_id, increment_messages=1)
            except Exception:
                logger.exception("failed to touch session %s after stream", session_id)

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
async def get_history(
    session_id: str,
    request: Request,
    store: StoreDep,
    upstream: UpstreamDep,
) -> HistoryResponse:
    """Fetch prior conversation messages from kaos-agents SessionMemory.

    Returns an empty list (not 404) when the session has no turns yet —
    the SPA seeds the transcript with whatever this returns on route mount.
    """
    # Ensure our metadata exists; if not, 404 here rather than letting
    # the upstream call leak a confusing message.
    try:
        await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    bearer = _bearer_from_request(request)
    r = await upstream.get(
        f"/v1/sessions/{session_id}/memory/messages",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    if r.status_code == 404:
        # Session exists in our sidecar but has no turns yet on the
        # agent side — return an empty history rather than 404ing.
        return HistoryResponse(session_id=session_id, turn_count=0, item_count=0, messages=[])
    if r.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"upstream /memory/messages {r.status_code}: {r.text[:300]}",
        )

    raw = r.json()
    # kaos-agents stores messages as 'user: ...' / 'assistant: ...'
    # strings inside `items[].content`. Split role from text.
    parsed: list[HistoryMessage] = []
    for item in raw.get("items", []):
        content_str = item.get("content", "")
        role: str = "assistant"
        text: str = content_str
        for prefix, mapped in (
            ("user: ", "user"),
            ("assistant: ", "assistant"),
            ("system: ", "system"),
        ):
            if content_str.startswith(prefix):
                role = mapped
                text = content_str[len(prefix) :]
                break
        parsed.append(
            HistoryMessage(
                role=role,  # type: ignore[arg-type]
                content=text,
                added_at=float(item.get("added_at", 0.0)),
            )
        )
    # kaos-agents returns newest-first; flip to chronological for the SPA.
    parsed.sort(key=lambda m: m.added_at)
    return HistoryResponse(
        session_id=session_id,
        turn_count=int(raw.get("turn_count", 0)),
        item_count=int(raw.get("item_count", len(parsed))),
        messages=parsed,
    )


@router.get("/sessions/{session_id}/transcript")
async def transcript_stub(session_id: str) -> dict[str, str]:
    """Transcript export is implemented client-side (see lib/transcript.ts).
    Server-side export for shareable-link use cases lives in a later phase."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="server-side transcript export not in v1; use the client-side download.",
    )
