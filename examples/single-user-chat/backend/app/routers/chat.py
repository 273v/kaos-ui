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
import os
from typing import Annotated, cast

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
from app.services.stream_proxy import _bearer_from_env
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


def _to_sse_event(ev: object) -> dict[str, str] | None:
    """Normalize an :func:`run_agentic_turn` yield into an SSE record.

    The orchestrator yields a mix of typed KaosEvent objects (its own
    AgenticLoop events) and raw SSE dicts forwarded verbatim from the
    worker. Both must land in the response stream as ``{event, data}``
    where ``data`` is a JSON string.

    - **dict** — already SSE-shaped. Returned unchanged.
    - **KaosEvent** — serialized via ``model_dump`` with the type
      discriminator injected so the SPA's reducer can switch on
      ``payload.type`` exactly as it does for the kaos-agents stream.

    Returns None for any unknown shape so the caller can skip it
    without breaking the stream.
    """
    if isinstance(ev, dict):
        # Already SSE-shaped {event, data}. ty narrows `dict` to
        # `dict[Unknown, Unknown]` from `object`, so go through a
        # checked cast to keep the public signature exact.
        return cast("dict[str, str]", ev)
    # Local import keeps the module-level dep graph minimal: chat.py
    # is imported at FastAPI startup, KaosEvent only when a turn fires.
    from kaos_agents.base.event import KaosEvent

    if isinstance(ev, KaosEvent):
        type_str = ev.event_type()
        payload = ev.model_dump(mode="json")
        # Inject the discriminator. KaosEvent stores `type` only as a
        # ClassVar (not a field), so the dump omits it; the SPA wire
        # contract puts ``type`` inside the payload dict.
        payload["type"] = type_str
        return {"event": type_str, "data": json.dumps(payload)}
    return None


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

    # Build a merged SessionPolicyWire from the current policy + the
    # partial body. M.6 — every body field is optional; only the
    # dimensions the caller passed get rewritten. The patch goes
    # through the canonical `policy=` path on SessionStore.patch so
    # auto_elevate / auto_loop / persona land on the live policy
    # (previously the handler built a legacy SessionToolSetWire which
    # carried only the 3 legacy fields, silently dropping the new
    # toggles — the source of the PlanActChip "stuck on Act" bug).
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

    policy_updates: dict[str, object] = {}
    if body.allowed_groups is not None:
        policy_updates["allowed_groups"] = list(body.allowed_groups)
    if body.denied_tools is not None:
        policy_updates["denied_tools"] = list(body.denied_tools)
    if body.auto_narrow is not None:
        policy_updates["auto_narrow"] = body.auto_narrow
    if body.auto_elevate is not None:
        policy_updates["auto_elevate"] = body.auto_elevate
    if body.auto_loop is not None:
        policy_updates["auto_loop"] = body.auto_loop
    if body.persona is not None:
        policy_updates["persona"] = body.persona
    # #312 — AgenticLoop budget caps.
    if body.max_loop_iterations is not None:
        policy_updates["max_loop_iterations"] = body.max_loop_iterations
    if body.max_loop_cost_usd is not None:
        policy_updates["max_loop_cost_usd"] = body.max_loop_cost_usd
    if body.max_loop_wall_clock_seconds is not None:
        policy_updates["max_loop_wall_clock_seconds"] = body.max_loop_wall_clock_seconds
    if policy_updates:
        new_policy = current.policy.model_copy(update=policy_updates)
    else:
        new_policy = current.policy

    return await store.patch(session_id, policy=new_policy)


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
        # the SessionToolSet filter (TR-2) to this list before sending
        # it as the wire-level `tools=` glob list; kaos-agents-serve
        # bridges those into kaos-llm-core Tool objects whose
        # definitions reach the LLM via the provider's native
        # tool-use API. The TR-6 planner narrows this further below.
        available_tool_names = tuple(sorted(runtime.tools.list_tools()))
    else:
        available_tool_names = ()

    # AgenticLoop input: one-line corpus headlines so the planner sees
    # enough to route without ballooning prompt cost. Always computed
    # (the legacy `auto_narrow` gate is gone — the loop's per-iteration
    # planner decides what to narrow).
    corpus_headlines: str = ""
    if runtime is not None:
        try:
            from app.services.uploads import list_session_files

            file_metas = await list_session_files(runtime=runtime, session_id=session_id)
            corpus_headlines = "\n".join(
                f"{m.filename} — {m.size_bytes} bytes, {m.content_type or 'unknown'}"
                for m in file_metas
            )
        except Exception:
            logger.exception("failed to render corpus headlines for session=%s", session_id)

    # First turn auto-derives a title from the user message so the
    # sidebar isn't a sea of "Untitled".
    is_first_turn = meta.message_count == 0 and meta.title == "Untitled"

    # Tee tool_call SSE events into a per-turn sidecar so /messages can
    # hydrate `tool_calls` on past assistant messages. Turn index is
    # derived from the pre-stream message_count (each turn = 2
    # messages: user + assistant), which is what touch(increment=2)
    # writes into the next session state.
    import secrets
    from typing import Any
    from urllib.parse import quote

    from starlette.background import BackgroundTask

    from app.services.persist_turn import persist_turn_completion
    from app.services.run_log import RunEventLog, read_active_pointer
    from app.services.tool_call_recorder import TurnToolCallRecorder, TurnUsageRecorder

    recorder = TurnToolCallRecorder()
    # #520: per-turn cost/token aggregator. Was previously not
    # instantiated, so SessionMeta.last_turn_cost_usd / last_turn_tokens
    # stayed at 0.0 even when the UI showed real cost via the
    # turn_summary cost_usd field. Observe the SSE stream alongside
    # the tool-call recorder.
    usage_recorder = TurnUsageRecorder()
    turn_index = meta.message_count // 2

    # SSE resume Stage 1: refuse a second concurrent POST. If
    # ``runs/active.json`` still says ``running`` for this session, the
    # SPA should be calling ``GET /runs/{run_id}/events`` instead. The
    # 409 body carries enough information for the SPA to open the
    # resume stream without re-querying ``runs/active``.
    if runtime is not None:
        try:
            active = await read_active_pointer(vfs=runtime.vfs, session_id=session_id)
        except Exception:  # noqa: BLE001 — never let pointer reads block the turn
            active = None
        if active is not None and active.get("status") == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "run_in_progress",
                    "what": "Another turn is still streaming for this session.",
                    "how_to_fix": (
                        "Wait for the existing run to finish or open "
                        "GET /v1/chat/sessions/{id}/runs/{run_id}/events to resume it."
                    ),
                    "run_id": active.get("run_id"),
                    "started_at": active.get("started_at"),
                    "alternative_tool": (
                        f"GET /v1/chat/sessions/{session_id}/runs/{active.get('run_id', '')}/events"
                    ),
                },
            )

    # Run id: deterministic ``turn-{idx:04d}`` prefix + 6 hex chars of
    # randomness. The prefix keeps log files sortable per session; the
    # suffix prevents collisions when the same turn index reruns (e.g.
    # after a soft retry that abandoned an earlier run). See design
    # §3.1.
    run_id = f"turn-{turn_index:04d}-{secrets.token_hex(3)}"

    # Open the durable run log BEFORE the upstream POST. ``run_log`` is
    # ``None`` only when the runtime isn't attached (test stubs); the
    # SSE generator below treats that as best-effort (no resume log).
    run_log: RunEventLog | None = None
    if runtime is not None:
        try:
            run_log = await RunEventLog.open(
                runtime=runtime,
                session_id=session_id,
                run_id=run_id,
                model=meta.model,
                turn_index=turn_index,
            )
        except Exception:  # noqa: BLE001 — log open failures must not break the turn
            logger.exception("failed to open run_log session=%s run=%s", session_id, run_id)
            run_log = None

    # Shared container for hand-off from the SSE generator to the
    # BackgroundTask. The generator populates ``records`` in its
    # ``finally:`` block (the only place we know streaming is done);
    # the BackgroundTask reads them after the response body has been
    # sent. Mutable list rather than a Future so we don't pay for
    # cross-task synchronization on a single-producer / single-
    # consumer hand-off.
    persist_snapshot: dict[str, Any] = {"records": [], "captured": False, "errored": False}

    async def _fetch_history(sid: str) -> list[HistoryMessage]:
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

    async def _do_persist() -> None:
        """BackgroundTask runner — invoked AFTER the SSE response body
        has been fully sent (Starlette's contract).

        The framework guarantees this runs even when the client
        disconnects, because the task is registered with the response
        object rather than the request scope. That's the load-bearing
        property the 2026-05-18 persona matrix found missing in the
        prior finally-block implementation.
        """
        try:
            if not persist_snapshot["captured"]:
                # Defensive: the generator should always populate the
                # snapshot in its ``finally:`` block, but a synchronous
                # exception before the first yield could skip it.
                return
            # UX-D1 (#427): the canonical-turn POST was previously in
            # the SSE generator's ``finally:`` block alongside the
            # snapshot capture, which made it vulnerable to
            # client-disconnect cancellation (the same failure mode the
            # 2026-05-18 persona matrix found for ``persist_turn_completion``).
            # Move it INTO the BackgroundTask so Starlette's
            # response-lifetime contract protects it. The snapshot
            # captures ``last_iter_text`` for hand-off.
            canonical_text = persist_snapshot.get("last_iter_text") or ""
            if canonical_text:
                try:
                    from app.services.agentic_worker import persist_canonical_turn

                    await persist_canonical_turn(
                        client=upstream,
                        bearer_token=bearer,
                        session_id=session_id,
                        user_message=body.message,
                        assistant_message=canonical_text,
                    )
                except Exception:
                    logger.exception(
                        "persist_canonical_turn failed session=%s",
                        session_id,
                    )
            await persist_turn_completion(
                store=store,
                session_id=session_id,
                is_first_turn=is_first_turn,
                user_message=body.message,
                sidecar_records=persist_snapshot["records"],
                runtime=runtime,
                turn_index=turn_index,
                fetch_history=_fetch_history,
                turn_cost_usd=float(persist_snapshot.get("turn_cost_usd") or 0.0),
                turn_tokens=int(persist_snapshot.get("turn_tokens") or 0),
            )
        finally:
            # SSE resume Stage 1: flip the active-pointer to a terminal
            # state so the SPA's ``runs/active`` poll stops returning
            # ``running`` for this run. We do this AFTER
            # ``persist_turn_completion`` so that anything depending on
            # the still-running pointer (none today, but reserved) sees
            # a coherent ordering. ``errored`` is set by the SSE
            # generator's exception handler.
            if run_log is not None:
                status_str: Any = "error" if persist_snapshot.get("errored") else "done"
                try:
                    await run_log.mark_done(status=status_str)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "failed to mark run done session=%s run=%s",
                        session_id,
                        run_id,
                    )

    # Per-run sequence fallback used when an event payload doesn't
    # carry ``payload["sequence"]`` (defensive — every kaos-agents
    # KaosEvent does today, but SPA-side envelopes and any future
    # synthetic frames may not). Starts at 0 so the leading
    # ``run_started`` envelope (id=-1) is strictly below the first
    # real event id.
    fallback_seq = {"value": 0}

    def _next_fallback_seq() -> int:
        v = fallback_seq["value"]
        fallback_seq["value"] = v + 1
        return v

    async def event_generator():
        # AgenticLoop wire-up: drive plan → elevate → execute → check →
        # replan via :func:`run_agentic_turn`. The orchestrator yields
        # a mix of typed KaosEvent objects (its own 4 events:
        # ToolPolicyElevated / CapabilityRequested / GoalChecked /
        # LoopTerminated) and verbatim SSE dicts forwarded from the
        # worker (text deltas, tool calls, usage, turn summary). Both
        # shapes need to land in the SSE stream as ``{event, data}``.
        from kaos_agents.patterns.agentic_loop import run_agentic_turn
        from kaos_agents.registry import default_tool_group_registry

        from app.services.agentic_worker import make_worker

        # SSE resume (Stage 1): emit a leading ``run_started`` envelope
        # so resume clients pulling from the JSONL log learn the
        # run_id, session_id, and started_at WITHOUT having to wait
        # for the first kaos-agents event. ``id: -1`` is intentionally
        # below any kaos-agents ``sequence`` (which starts at 0) so a
        # client reconnecting with ``Last-Event-ID: -1`` replays from
        # the very start. Written to the JSONL FIRST so it shows up at
        # the head of any resume stream.
        run_started_payload = {
            "type": "run_started",
            "run_id": run_id,
            "session_id": session_id,
            "turn_index": turn_index,
            "started_at": run_log.started_at if run_log is not None else None,
            "model": meta.model,
        }
        if run_log is not None:
            try:
                await run_log.append("run_started", run_started_payload, sequence=-1)
            except Exception:  # noqa: BLE001
                pass
        yield {
            "event": "run_started",
            "data": json.dumps(run_started_payload),
            "id": "-1",
        }

        # The planner Signature owns the kept_groups decision (see
        # kaos-agents `_TurnToolPolicySignature` docstring — its
        # corpus-kinds hints already favor `documents` when files are
        # attached and the question references the document). Earlier
        # this block force-elevated documents+vfs from the chat router
        # as a belt-and-suspenders workaround; that created two
        # sources of truth for the policy and was deleted as part of
        # the thin-worker-prompt refactor. The planner is the policy.
        # See kaos-modules/docs/plans/thin-worker-prompt.md M1.
        session_policy = meta.policy.to_session_policy()
        available_groups = sorted(default_tool_group_registry.list_names())
        # #446 cost-guard fix: the per-iteration worker cap MUST defer
        # to the session policy's `max_loop_cost_usd` (which is the
        # user-set per-turn budget) rather than the env-default
        # `settings.turn_budget_usd`. Pre-fix, a session with a
        # `$0.25` policy was being given a `$5.00` worker cap, and a
        # single iteration could spend $12+ before the AgenticLoop's
        # cumulative `_budget_exceeded` check (which only fires AFTER
        # the iteration completes) saw the overrun. Use the smaller of
        # the two so the env-default still serves as a hard ceiling
        # for sessions whose policy is intentionally unbounded.
        per_iteration_budget = min(settings.turn_budget_usd, meta.policy.max_loop_cost_usd)
        worker = make_worker(
            client=upstream,
            bearer_token=bearer,
            meta=meta,
            max_cost_usd=per_iteration_budget,
            available_tool_names=available_tool_names or None,
            corpus_markdown=corpus_markdown,
        )

        # Iteration-leak fix (task #458, plan
        # docs/plans/2026-05-19-agentic-loop-honesty.md §3.1.a). The
        # worker tagged every upstream POST with
        # ``is_internal_iteration=True`` on iteration > 1 so kaos-agents
        # skipped the user + intermediate-assistant memory writes. We
        # accumulate the final iteration's assistant text from the
        # streamed text_deltas here and POST the canonical (user, final)
        # pair to /v1/sessions/{id}/memory/messages/turn after the loop
        # terminates so SessionMemory.MESSAGES has exactly one user
        # entry + one assistant entry per turn no matter how many
        # critic iterations the loop ran.
        iter_text_parts: list[str] = []
        last_iter_text: str = ""
        # #519: tracks whether the previous turn_summary closed the
        # stream. The NEXT text_delta after a closed stream begins a
        # new phase (typically the AgenticLoop's refusal lead text
        # after a terminator) and should REPLACE rather than append —
        # mirroring the SPA event-handler's #508 logic so MEMORY
        # persists exactly what the UI rendered.
        streaming_closed: bool = False
        try:
            # M2 reasoning-action consistency critic — gates the
            # ``satisfied`` verdict on whether the worker's response
            # contradicts its own body or the tool results. When it
            # fires, the loop force-iterates with an M2-derived
            # thinking_note directive. Off when env var unset so
            # operators can toggle without a code change.
            m2_consistency_model = (
                os.environ.get(
                    "KAOS_AGENT_M2_CONSISTENCY_MODEL",
                    "anthropic:claude-haiku-4-5",
                )
                or None
            )
            async for ev in run_agentic_turn(
                user_message=body.message,
                policy=session_policy,
                worker=worker,
                available_groups=available_groups,
                session_id=session_id,
                run_id=run_id,
                # corpus_kinds: future magika-classified content-type
                # labels for uploaded files (kaos-nlp-core P2-1d). Empty
                # for now — planner gracefully handles missing values.
                corpus_kinds=[],
                session_intent=meta.policy.persona,
                corpus_headlines=corpus_headlines,
                # recent_turns: deferred to TR-13 (deeper context). The
                # planner tolerates an empty string.
                recent_turns="",
                m2_consistency_model=m2_consistency_model,
            ):
                sse_event = _to_sse_event(ev)
                if sse_event is None:
                    continue
                # SSE resume Stage 1: stamp every frame with ``id:``
                # so EventSource clients can ``Last-Event-ID``-resume.
                # kaos-agents events carry a per-run monotonic counter
                # at ``payload["sequence"]`` (``EventEmitter._sequence``);
                # use that when present and fall back to a local
                # counter so frames without ``sequence`` still get a
                # unique, ordered id.
                payload: Any = None
                event_name = sse_event.get("event", "")
                try:
                    payload = json.loads(sse_event["data"]) if "data" in sse_event else None
                except Exception:
                    payload = None
                seq_raw = payload.get("sequence") if isinstance(payload, dict) else None
                if isinstance(seq_raw, int):
                    sequence = seq_raw
                else:
                    sequence = _next_fallback_seq()
                sse_event["id"] = str(sequence)
                # Persist BEFORE yielding so resume clients connecting
                # the instant after the live consumer drops the frame
                # still see it. The append is best-effort; a write
                # failure logs internally and the live stream keeps
                # flowing.
                if run_log is not None and isinstance(payload, dict):
                    try:
                        await run_log.append(event_name, payload, sequence=sequence)
                    except Exception:
                        pass
                # Best-effort tap: parsing failures must not corrupt
                # the stream. Both recorders ignore events they don't
                # know. Single try block — neither call should be able
                # to raise, but if one does we still want the other to
                # have a chance on subsequent events.
                try:
                    recorder.observe(event_name, payload)
                    usage_recorder.observe(event_name, payload)
                except Exception:
                    pass

                # Iteration-leak fix companion accumulator. Mirrors the
                # SPA event-handler.ts state machine so MEMORY persists
                # exactly what the UI rendered (closes #519: memory ≠ UI).
                #
                # Each worker iteration emits text_delta* → turn_summary.
                # When a refusal terminator fires AFTER a successful
                # worker iteration, it emits another text_delta +
                # turn_summary(intent="refuse"). The UI applies #508:
                # the post-turn-summary text_delta REPLACES (not
                # concatenates) the previous content. We mirror that
                # here so ``last_iter_text`` matches the UI exactly.
                if isinstance(payload, dict):
                    ptype = payload.get("type")
                    if ptype == "text_delta":
                        content = payload.get("content")
                        if isinstance(content, str):
                            if streaming_closed and content:
                                # #508 mirror: the previous turn_summary
                                # closed the stream; this delta begins
                                # a new phase (typically the refusal
                                # lead). REPLACE the prior text rather
                                # than concatenate.
                                last_iter_text = ""
                                iter_text_parts.clear()
                                streaming_closed = False
                            iter_text_parts.append(content)
                    elif ptype == "turn_summary":
                        candidate = "".join(iter_text_parts)
                        # Prefer the worker's own concatenated text
                        # field when populated; the SSE deltas are the
                        # ground truth otherwise.
                        summary_text = payload.get("text")
                        if isinstance(summary_text, str) and summary_text:
                            candidate = summary_text
                        if candidate:
                            last_iter_text = candidate
                        iter_text_parts.clear()
                        # Mark stream-closed so the NEXT text_delta
                        # knows it's starting a new phase and should
                        # replace rather than append.
                        streaming_closed = True

                yield sse_event
        except Exception:
            # Any uncaught exception in the loop means the turn
            # errored. Flag it so ``_do_persist`` marks the run as
            # ``error`` in the active pointer.
            persist_snapshot["errored"] = True
            raise
        finally:
            # All we do here is snapshot the recorder state so the
            # BackgroundTask attached to the response below can read
            # records by value after streaming completes. The actual
            # durable writes happen there, NOT here — see
            # ``kaos-modules/docs/plans/persona-matrix-followups.md``
            # §7 and task UX-D1 for why finally-block awaits are
            # vulnerable to client-disconnect cancellation.
            persist_snapshot["records"] = (
                list(recorder.records()) if not recorder.is_empty() else []
            )
            # #520: hand off the per-turn cost/token aggregate so
            # persist_turn_completion can patch SessionMeta with the
            # real numbers instead of the previous 0.0 defaults.
            turn_cost_usd, turn_tokens = usage_recorder.snapshot()
            persist_snapshot["turn_cost_usd"] = turn_cost_usd
            persist_snapshot["turn_tokens"] = turn_tokens
            persist_snapshot["captured"] = True

            # Iteration-leak fix (task #458). Companion to the
            # worker's per-iteration ``is_internal_iteration=True``
            # flag — POST the canonical (user, final-assistant) pair
            # to kaos-agents' new /memory/messages/turn endpoint so
            # SessionMemory.MESSAGES has exactly one user entry + one
            # assistant entry for this turn (no matter how many critic
            # iterations the loop ran).
            #
            # #504 follow-up: if the loop terminated without a closing
            # ``turn_summary`` event for the final iteration (abrupt
            # client disconnect, upstream stream truncation, a
            # terminator that emits text_delta + LoopTerminated without
            # the wrapping turn_summary), the unflushed
            # ``iter_text_parts`` still represent the most-recent text
            # the user saw. Merge them in BEFORE the persist so memory
            # captures the same final text as the UI rendered.
            if iter_text_parts:
                tail = "".join(iter_text_parts)
                if tail and tail != last_iter_text:
                    last_iter_text = tail
                iter_text_parts.clear()
            # UX-D1 (#427): hand off ``last_iter_text`` to the
            # BackgroundTask via ``persist_snapshot`` instead of
            # awaiting ``persist_canonical_turn`` here. Awaiting INSIDE
            # the SSE generator's ``finally:`` block is vulnerable to
            # client-disconnect cancellation. Starlette's
            # ``BackgroundTask`` is the safe place — it runs after the
            # response body is fully sent regardless of client state.
            persist_snapshot["last_iter_text"] = last_iter_text

    return EventSourceResponse(
        event_generator(),
        ping=15,
        # ``X-Kaos-Run-Id`` lets the SPA stash the run id synchronously
        # off the response headers without waiting for the leading
        # ``run_started`` envelope — see design §3.1.
        headers={"X-Accel-Buffering": "no", "X-Kaos-Run-Id": run_id},
        # Starlette runs ``_do_persist`` AFTER the response body is
        # fully sent. The framework owns the lifetime, so a client
        # disconnect during streaming doesn't cancel these writes —
        # which closes the bug surfaced by the 2026-05-18 persona
        # matrix where 8/10 sessions stuck at ``Untitled`` /
        # ``message_count=0``.
        background=BackgroundTask(_do_persist),
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
    # this feature shipped) — or any turn whose SSE stream client
    # disconnected before the sidecar flush — have an empty/missing
    # sidecar. For those, we fall back to deriving tool_calls from
    # kaos-agents' memory/actions endpoint. The fallback loses
    # args_preview (the API drops structured args) but at minimum tells
    # the user *which* tools ran with what result — the difference
    # between "I see 0 chips and assume the agent did nothing" and "I
    # see 9 chips telling me kaos-source-fr-search ran six times".
    runtime = getattr(request.app.state, "kaos_runtime", None)
    if runtime is not None:
        from app.models import HistoryToolCall
        from app.services.tool_call_recorder import (
            parse_actions_into_records,
            parse_records_jsonl,
            turn_sidecar_path,
        )

        # #401 (SES1): legacy sessions created against kaos-agents pre-a18
        # have N assistant messages per logical turn (one per AgenticLoop
        # iteration) because the per-iteration persist landed before the
        # #458 / #504 canonical-turn fix. The sidecar at
        # ``toolcalls/turn-{N:04d}.jsonl`` was always written ONCE per
        # logical turn — keyed by the user-message count at the time of
        # the SSE stream. Using ``assistant_index`` as the sidecar key
        # mis-aligns: assistant[0]=iter1 looks up turn-0000.jsonl, gets
        # the chips, then assistant[1]=iter2 looks up turn-0001.jsonl
        # which doesn't exist, falls back to memory/actions, and the
        # chips "bleed" across turns.
        #
        # Fix: derive turn_index from the count of *user* messages that
        # precede each assistant message. Two assistants in a row (same
        # logical turn) get the same turn_index — only the LAST one in
        # the group should claim the sidecar to avoid double-attaching.
        assistant_msgs = [m for m in parsed if m.role == "assistant"]
        turn_index_by_msg: dict[int, int] = {}
        sidecar_owner_by_msg: dict[int, bool] = {}
        user_seen = 0
        last_assistant_in_group: HistoryMessage | None = None
        for m in parsed:
            if m.role == "user":
                # Close any open assistant group: the previous final
                # assistant message owns its turn's sidecar.
                if last_assistant_in_group is not None:
                    sidecar_owner_by_msg[id(last_assistant_in_group)] = True
                    last_assistant_in_group = None
                user_seen += 1
            elif m.role == "assistant":
                # turn_index is 0-based count of user messages BEFORE
                # this assistant — i.e. (user_seen - 1) for the typical
                # "user → assistant" cadence.
                turn_index_by_msg[id(m)] = max(user_seen - 1, 0)
                # Mark not-owner; the last assistant in this group wins.
                sidecar_owner_by_msg[id(m)] = False
                last_assistant_in_group = m
        # Close the trailing group (final turn).
        if last_assistant_in_group is not None:
            sidecar_owner_by_msg[id(last_assistant_in_group)] = True

        # Back-compat: legacy sessions where the only assistant per turn
        # ALSO has a sidecar — assistant_indices == turn_index_by_msg
        # for sessions that never iterated. The dedup only kicks in for
        # the pathological pre-a18 case.
        assistant_indices: dict[int, int] = dict(turn_index_by_msg)

        # Per-message sidecar hydration first (the rich path — has args).
        msgs_needing_fallback: list[HistoryMessage] = []
        for msg in assistant_msgs:
            if not sidecar_owner_by_msg.get(id(msg), True):
                # Iteration leaf within a multi-iteration turn: do not
                # claim a sidecar (the final assistant in the group
                # does). Leaves tool_calls empty for the leaf, which is
                # correct — the leaf was an intermediate critic-rejected
                # response, not the user-facing answer.
                continue
            path = turn_sidecar_path(session_id, assistant_indices[id(msg)])
            try:
                blob = await runtime.vfs.read(path)
                records = parse_records_jsonl(blob)
            except Exception:
                records = []
            if records:
                msg.tool_calls = [
                    HistoryToolCall(
                        id=r.id,
                        name=r.name,
                        status=r.status,
                        args_preview=r.args_preview,
                        result_preview=r.result_preview,
                    )
                    for r in records
                ]
            else:
                msgs_needing_fallback.append(msg)

        # Fallback: pull memory/actions once, partition by assistant
        # message timestamp, attach. We accept the cost of one extra
        # round-trip per /messages call ONLY when at least one assistant
        # turn is missing its sidecar.
        if msgs_needing_fallback:
            try:
                actions_resp = await upstream.get(
                    f"/v1/sessions/{session_id}/memory/actions",
                    headers={"Authorization": f"Bearer {bearer}"},
                )
                actions_resp.raise_for_status()
                actions_items = list(actions_resp.json().get("items", []))
            except Exception:
                actions_items = []

            if actions_items:
                # kaos-agents returns newest-first; reverse to match
                # message chronology so the per-turn partition works.
                actions_items.reverse()
                # For each missing-sidecar assistant message, take the
                # slice of actions whose added_at falls in this message's
                # turn window. Turn window = (prev assistant ts, this
                # assistant ts]; for the first assistant message, lower
                # bound is 0. This is best-effort — action timestamps
                # land between user-send and assistant-finish, both of
                # which are bracketed by the assistant message's own
                # added_at. It's good enough for single-turn sessions
                # (the common case where this fallback fires) and
                # degrades gracefully for multi-turn.
                prev_ts = 0.0
                for msg in assistant_msgs:
                    window = [
                        a
                        for a in actions_items
                        if prev_ts < float(a.get("added_at", 0.0)) <= msg.added_at + 1.0
                    ]
                    prev_ts = msg.added_at
                    if msg not in msgs_needing_fallback:
                        continue
                    records = parse_actions_into_records(window)
                    if not records:
                        continue
                    msg.tool_calls = [
                        HistoryToolCall(
                            id=r.id,
                            name=r.name,
                            status=r.status,
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


# ---------------------------------------------------------------------------
# Audit trace — #447 closes the recorder vs memory.json undercount confusion.
#
# The per-turn sidecar at ``sessions/{id}/toolcalls/turn-NNNN.jsonl`` is the
# wire-level subset (chip UI surface). The canonical full trace lives in
# kaos-agents' ``SessionMemory.ACTIONS`` and is reachable via the upstream
# ``/v1/sessions/{id}/memory/actions`` endpoint. This SPA-side endpoint
# proxies that canonical source so external consumers (kaos-audit-session
# CLI, debug overlays, downstream analytics) have one URL to hit without
# needing to know about the upstream kaos-agents API or fetching the bearer
# token themselves.
#
# Semantics:
#   GET /v1/chat/sessions/{id}/audit-trace -> JSON {"items": [...]}
#   Each item is one MemoryActions row: tool_name, args, result_summary,
#   duration_ms, is_error, added_at, plan_id, step_id, etc.
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/audit-trace")
async def get_audit_trace(
    session_id: str,
    request: Request,
    store: StoreDep,
    upstream: UpstreamDep,
) -> Response:
    """#447 — canonical full action trace for one session.

    Reads ``SessionMemory.ACTIONS`` via the upstream kaos-agents endpoint
    and returns it verbatim. This is the authoritative source for full
    agent activity (including planner / critic / Signature LLM calls
    that don't surface as wire-level tool chips).

    External consumers that need to audit an agent run should hit THIS
    endpoint, not the per-turn sidecar JSONL. The sidecar is the wire-
    level subset for chip-UI rendering only.
    """
    try:
        await store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    bearer = _bearer_from_request(request)
    r = await upstream.get(
        f"/v1/sessions/{session_id}/memory/actions",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    if r.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "what": f"upstream returned {r.status_code} fetching memory/actions",
                "how_to_fix": "retry; if persistent, check kaos-agents API health",
                "alternative": "read the per-turn sidecar JSONL for the wire-level subset",
            },
        )
    return Response(
        content=r.text,
        media_type="application/json",
    )
