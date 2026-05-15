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

import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sse_starlette import EventSourceResponse

from app.auth import require_auth
from app.deps import get_session_store, get_settings, get_upstream_client
from app.exceptions import SessionNotFoundError
from app.logging_setup import app_logger
from app.models import (
    ArchiveResponse,
    CategoriesResponse,
    CategoryInfo,
    CreateSessionBody,
    HistoryMessage,
    HistoryResponse,
    PatchMetaBody,
    SendMessageBody,
    SessionListResponse,
    SessionMeta,
    SessionToolSetWire,
    ToolSetUpdateBody,
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


# ── tool policy (TR-4) ────────────────────────────────────────────────


@router.get("/categories", response_model=CategoriesResponse)
async def list_categories() -> CategoriesResponse:
    """Return the available tool categories for SessionMeta.tool_set.

    Sourced from kaos-agents' ``default_tool_group_registry`` joined
    with the kaos-ui ``KAOS_TOOL_GROUP_DESCRIPTIONS`` map. Order is
    stable — sorted by group id — so the SPA can cache.

    The ``default_enabled`` field reflects what a fresh session would
    include in its ceiling (documents/citations/vfs True; web False).
    """
    from kaos_agents.registry import default_tool_group_registry
    from kaos_ui.agents import KAOS_TOOL_GROUP_DESCRIPTIONS

    default_ceiling = set(SessionToolSetWire().allowed_groups)

    _LABELS = {
        "web": "Web sources",
        "documents": "Documents",
        "citations": "Citations",
        "vfs": "File browser",
    }

    rows: list[CategoryInfo] = []
    for group in sorted(default_tool_group_registry.groups(), key=lambda g: g.name):
        if group.name not in KAOS_TOOL_GROUP_DESCRIPTIONS:
            # Defensive: a downstream consumer registered a group kaos-ui
            # doesn't have a description for. Surface it with a generic
            # label so the UI doesn't 500.
            label = group.name.capitalize()
            desc = group.description
        else:
            label = _LABELS.get(group.name, group.name.capitalize())
            desc = KAOS_TOOL_GROUP_DESCRIPTIONS[group.name]
        rows.append(
            CategoryInfo(
                id=group.name,
                label=label,
                description=desc,
                default_enabled=group.name in default_ceiling,
                tool_count=len(group.tool_names),
            )
        )
    return CategoriesResponse(categories=rows)


@router.patch("/sessions/{session_id}/tool-set", response_model=SessionMeta)
async def patch_tool_set(session_id: str, body: ToolSetUpdateBody, store: StoreDep) -> SessionMeta:
    """Update a session's tool ceiling. Fields are partial — omit a
    dimension to keep the existing value.

    Unknown group names return 422 with the offending name(s) so the
    SPA can surface the problem inline. The server NEVER silently
    drops an unknown group; defensive because the SPA's local cache
    of categories may drift from the backend.
    """
    from kaos_agents.registry import default_tool_group_registry

    try:
        current = await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    new_tool_set = current.tool_set.model_copy()
    if body.allowed_groups is not None:
        known = set(default_tool_group_registry.list_names())
        unknown = [g for g in body.allowed_groups if g not in known]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "what": f"unknown tool group(s): {unknown!r}",
                    "how_to_fix": (
                        "Call GET /v1/chat/categories for the known set. "
                        "Group names are case-sensitive."
                    ),
                    "alternative": "Pass [] to fully disable tools for this session.",
                },
            )
        new_tool_set = new_tool_set.model_copy(update={"allowed_groups": body.allowed_groups})
    if body.denied_tools is not None:
        new_tool_set = new_tool_set.model_copy(update={"denied_tools": body.denied_tools})
    if body.auto_narrow is not None:
        new_tool_set = new_tool_set.model_copy(update={"auto_narrow": body.auto_narrow})

    return await store.patch(session_id, tool_set=new_tool_set)


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

    # P2-4: per-turn model override (the "Re-run with different model"
    # affordance). Mutates the local meta copy for this turn only; the
    # persisted SessionMeta.model is untouched so the next un-overridden
    # turn falls back to the session's chosen default.
    if body.model is not None and body.model != meta.model:
        _validate_model_id(body.model)
        meta = meta.model_copy(update={"model": body.model})

    bearer = _bearer_from_request(request)
    runtime = getattr(request.app.state, "kaos_runtime", None)

    # P2-2: when there are uploaded files in this session, inline a
    # markdown rendering of each ready-parsed file into the system
    # prompt so the agent can ground its answer in the content.
    # kaos-agents 0.1.0a1's MessageRequest doesn't accept a per-turn
    # corpus= so this prompt-side approach is the available wire.
    corpus_markdown: str = ""
    if runtime is not None:
        from app.services.uploads import render_session_corpus_markdown

        try:
            corpus_markdown = await render_session_corpus_markdown(
                runtime=runtime, session_id=session_id
            )
        except Exception:
            logger.exception("failed to render corpus for session=%s", session_id)

    available_tool_names: tuple[str, ...]
    if meta.tools_enabled and runtime is not None:
        # Names of every tool currently registered. The proxy applies
        # the SessionToolSet filter (TR-2) to this list; we also pass
        # it through to `augment_instructions` so the system prompt
        # tells the agent what's available. The TR-6 planner narrows
        # this further below.
        available_tool_names = tuple(sorted(runtime.tools.list_tools()))
    else:
        available_tool_names = ()

    # TR-6: when auto_narrow is on, run the TurnToolPolicy planner to
    # narrow this turn's tool set within the ceiling. Result is a
    # per-turn `tool_set_override` handed to stream_chat. Emitting the
    # decision as an SSE event happens below (in event_generator) so
    # the SPA can render a transparency badge.
    from app.models import SessionToolSetWire
    from app.services.turn_tool_policy import TurnToolPolicy, plan_turn_tool_policy

    tool_policy_event: TurnToolPolicy | None = None
    effective_tool_set: SessionToolSetWire | None = None
    if meta.tools_enabled and meta.tool_set.auto_narrow:
        # Build the planner inputs — corpus headlines + recent turns
        # compressed to one line each so the planner sees enough to
        # route without ballooning prompt cost.
        if runtime is not None:
            try:
                from app.services.uploads import list_session_files

                metas = await list_session_files(runtime=runtime, session_id=session_id)
                corpus_headlines = "\n".join(
                    f"{m.filename} — {m.size_bytes} bytes, {m.content_type or 'unknown'}"
                    for m in metas
                )
            except Exception:
                corpus_headlines = ""
        else:
            corpus_headlines = ""
        try:
            tool_policy_event = await plan_turn_tool_policy(
                user_message=body.message,
                recent_turns="",  # TR-6 keeps history empty; TR-13 docs deeper context
                corpus_headlines=corpus_headlines,
                ceiling_groups=list(meta.tool_set.allowed_groups),
                available_groups=list(meta.tool_set.allowed_groups),
            )
            # Intersect ceiling with planner choice — already done inside
            # the planner, but compose a fresh SessionToolSetWire for the
            # proxy that pins this turn's narrowed groups + keeps the
            # session's denied_tools floor.
            effective_tool_set = SessionToolSetWire(
                allowed_groups=sorted(tool_policy_event.turn_groups),
                denied_tools=list(meta.tool_set.denied_tools),
                auto_narrow=False,  # already narrowed for this turn
            )
        except Exception:
            logger.exception("turn-policy planner failed; using ceiling")
            tool_policy_event = None
            effective_tool_set = None

    # First turn auto-derives a title from the user message so the
    # sidebar isn't a sea of "Untitled".
    is_first_turn = meta.message_count == 0 and meta.title == "Untitled"

    # Tee tool_call SSE events into a per-turn sidecar so /messages can
    # hydrate `tool_calls` on past assistant messages. Turn index is
    # derived from the pre-stream message_count (each turn = 2
    # messages: user + assistant), which is what touch(increment=2)
    # writes into the next session state.
    from app.services.tool_call_recorder import (
        TurnToolCallRecorder,
        serialize_records,
        turn_sidecar_path,
    )

    recorder = TurnToolCallRecorder()
    turn_index = meta.message_count // 2

    async def event_generator():
        # TR-7 wire: emit ToolPolicyDecided before the first kaos-agents
        # event so the SPA sees the narrowing decision before any tool
        # call lands. Always emitted when the planner ran, even if it
        # fell back to the ceiling — that itself is information.
        if tool_policy_event is not None:
            yield {
                "event": "tool_policy_decided",
                "data": json.dumps(
                    {
                        "type": "tool_policy_decided",
                        "turn_groups": sorted(tool_policy_event.turn_groups),
                        "ceiling_groups": list(meta.tool_set.allowed_groups),
                        "reasoning": tool_policy_event.reasoning,
                        "confidence": tool_policy_event.confidence,
                        "fell_back_to_ceiling": tool_policy_event.fell_back_to_ceiling,
                        "cost_usd": tool_policy_event.cost_usd,
                        "latency_ms": tool_policy_event.latency_ms,
                    }
                ),
            }
        try:
            async for evt in stream_chat(
                client=upstream,
                bearer_token=bearer,
                meta=meta,
                message=body.message,
                max_cost_usd=settings.turn_budget_usd,
                available_tool_names=available_tool_names,
                corpus_markdown=corpus_markdown,
                tool_set_override=effective_tool_set,
            ):
                # Best-effort tap: parsing failures must not corrupt the
                # stream. The recorder ignores events it doesn't know.
                try:
                    payload = json.loads(evt["data"]) if "data" in evt else None
                    recorder.observe(evt.get("event", ""), payload)
                except Exception:
                    pass
                yield evt
        finally:
            # Persist the sidecar BEFORE the title/touch work so a failure
            # in the LLM-titler doesn't lose tool-call history.
            if not recorder.is_empty() and runtime is not None:
                try:
                    blob = serialize_records(recorder.records())
                    await runtime.vfs.write(turn_sidecar_path(session_id, turn_index), blob)
                except Exception:
                    logger.exception(
                        "failed to persist tool-call sidecar session=%s turn=%d",
                        session_id,
                        turn_index,
                    )
            # Increment by 1: a turn is (user message + assistant reply),
            # not two messages. Set title on first turn from the user
            # input as an IMMEDIATE heuristic so the sidebar updates
            # right away — the LLM auto-titler runs as a background
            # task and replaces it with something better a moment
            # later (and again every 10 turns / 24h, until the user
            # renames manually).
            try:
                if is_first_turn:
                    await store.patch(
                        session_id,
                        title=_derive_title(body.message),
                        title_source="auto",
                    )
                await store.touch(session_id, increment_messages=2)
            except Exception:
                logger.exception("failed to touch session %s after stream", session_id)

            # Fire-and-forget LLM-titler. We don't await this — the
            # caller has already received the full SSE stream, and the
            # title patch will surface on the next sidebar refresh.
            try:
                import asyncio

                from app.services.title import maybe_retitle_session

                async def _fetch_history(sid: str):
                    from urllib.parse import quote

                    r = await upstream.get(
                        f"/v1/sessions/{quote(sid)}/memory/messages",
                        headers={"Authorization": f"Bearer {bearer}"},
                    )
                    if r.status_code >= 400:
                        return []
                    raw = r.json()
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
                    parsed.sort(key=lambda m: m.added_at)
                    return parsed

                # Fire-and-forget the auto-titler. We deliberately don't keep
                # a reference — the task self-cancels on shutdown via the
                # default loop policy. RUF006 is suppressed here since
                # cancellation isn't required for correctness.
                _ = asyncio.create_task(  # noqa: RUF006
                    maybe_retitle_session(
                        store=store,
                        session_id=session_id,
                        fetch_history=_fetch_history,
                    )
                )
            except Exception:
                logger.exception("failed to schedule auto-titler for %s", session_id)

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

    # Hydrate per-turn tool_calls from the sidecars we wrote during chat.
    # The N-th assistant message in chronological order corresponds to
    # toolcalls/turn-{N:04d}.jsonl. Pre-existing sessions (created before
    # this feature shipped) have no sidecars — assistant messages without
    # a matching file just get an empty tool_calls list.
    runtime = getattr(request.app.state, "kaos_runtime", None)
    if runtime is not None:
        from app.models import HistoryToolCall
        from app.services.tool_call_recorder import parse_records_jsonl, turn_sidecar_path

        assistant_index = 0
        for msg in parsed:
            if msg.role != "assistant":
                continue
            path = turn_sidecar_path(session_id, assistant_index)
            assistant_index += 1
            try:
                blob = await runtime.vfs.read(path)
            except Exception:
                # Missing sidecar (pre-existing turn or VFS miss) is the
                # common case — no logging.
                continue
            records = parse_records_jsonl(blob)
            msg.tool_calls = [
                HistoryToolCall(
                    id=r.id,
                    name=r.name,
                    status=r.status,  # type: ignore[arg-type]
                    args_preview=r.args_preview,
                    result_preview=r.result_preview,
                )
                for r in records
            ]

    return HistoryResponse(
        session_id=session_id,
        turn_count=int(raw.get("turn_count", 0)),
        item_count=int(raw.get("item_count", len(parsed))),
        messages=parsed,
    )


def _transcript_markdown(meta: SessionMeta, messages: list[HistoryMessage]) -> str:
    """Render a transcript as agent-readable markdown.

    Used by both the client-side markdown download (returned as-is)
    and the DOCX export (parsed back to ContentDocument before
    serializing). The ``> _attribution_`` blockquote on each
    assistant turn carries cost / tokens / tool calls — the same
    shape that FEAT-6 surfaced in the JSON export.
    """
    parts: list[str] = [f"# {meta.title}", "", f"_Model: `{meta.model}`_", ""]
    for m in messages:
        if m.role == "user":
            parts.append("## You")
        elif m.role == "assistant":
            parts.append("## Assistant")
        else:
            parts.append(f"## {m.role.capitalize()}")
        parts.append("")
        parts.append(m.content)
        if m.role == "assistant" and m.tool_calls:
            attribution = ", ".join(f"`{tc.name}`" for tc in m.tool_calls)
            parts.append("")
            parts.append(f"> _Tools: {attribution}_")
        parts.append("")
    return "\n".join(parts)


@router.get("/sessions/{session_id}/transcript")
async def transcript_export(
    session_id: str,
    request: Request,
    store: StoreDep,
    upstream: UpstreamDep,
    format: str = "markdown",
) -> Response:
    """P2-4 — server-side transcript export. Supports ``markdown``,
    ``json``, and ``docx``. The DOCX path runs the markdown through
    ``kaos_content.parse_markdown`` → ``kaos_office.docx.write_docx_bytes``
    so the output preserves headings, lists, bold/italic, and code
    fences instead of being a plain-text dump."""
    fmt = format.lower()
    if fmt not in ("markdown", "json", "docx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "what": f"unsupported transcript format {format!r}",
                "how_to_fix": "use one of: markdown, json, docx",
            },
        )

    # Reuse the existing history fetch path. We can't call get_history
    # directly because it's a FastAPI handler; pull the upstream call
    # inline instead.
    try:
        meta = await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    bearer = _bearer_from_request(request)
    r = await upstream.get(
        f"/v1/sessions/{session_id}/memory/messages",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    messages: list[HistoryMessage] = []
    if r.status_code < 400:
        raw = r.json()
        for item in raw.get("items", []):
            content_str = item.get("content", "")
            role = "assistant"
            text = content_str
            for prefix, mapped in (
                ("user: ", "user"),
                ("assistant: ", "assistant"),
                ("system: ", "system"),
            ):
                if content_str.startswith(prefix):
                    role = mapped
                    text = content_str[len(prefix) :]
                    break
            messages.append(
                HistoryMessage(
                    role=role,  # type: ignore[arg-type]
                    content=text,
                    added_at=float(item.get("added_at", 0.0)),
                )
            )
        messages.sort(key=lambda m: m.added_at)

    if fmt == "markdown":
        body = _transcript_markdown(meta, messages)
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{meta.title}.md"',
            },
        )

    if fmt == "json":
        body = HistoryResponse(
            session_id=session_id,
            turn_count=len(messages),
            item_count=len(messages),
            messages=messages,
        ).model_dump_json(indent=2)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{meta.title}.json"',
            },
        )

    # fmt == "docx" — round-trip via kaos-content + kaos-office writers.
    try:
        from kaos_content.parsers import parse_markdown
        from kaos_office.docx import write_docx_bytes
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "what": "DOCX export is unavailable",
                "how_to_fix": "install the kaos-office + kaos-content extras",
                "alternative": "use format=markdown or format=json",
            },
        ) from exc

    md = _transcript_markdown(meta, messages)
    doc = parse_markdown(md)
    docx_bytes = write_docx_bytes(doc)
    return Response(
        content=docx_bytes,
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers={
            "Content-Disposition": f'attachment; filename="{meta.title}.docx"',
        },
    )
