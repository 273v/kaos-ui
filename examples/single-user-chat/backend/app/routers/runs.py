"""/v1/chat/sessions/{id}/runs/* — SSE resume endpoints (Stage 1).

Two routes, both gated by the shared ``require_auth`` dependency:

* ``GET /sessions/{id}/runs/active`` — returns the current
  ``active.json`` pointer (or ``null`` when no run has ever been
  recorded). The SPA polls this on session-mount to decide whether
  to fall back to the resume stream.
* ``GET /sessions/{id}/runs/{run_id}/events`` — replays the JSONL
  log as an SSE stream. Each emitted frame carries ``id:`` set to
  the event's ``seq`` so an EventSource client can reconnect with
  ``Last-Event-ID``. Honors a ``?after_seq=N`` query parameter and
  the ``Last-Event-ID`` request header per the EventSource spec.

Stage 1 is **replay-only**. We read whatever events have been
written to the JSONL at request time and stream them out, then
close — even if the active pointer still says ``running``. Live
tail (waiting on an in-process bell for new writes) lands in
Stage 2.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sse_starlette import EventSourceResponse

from app.auth import require_auth
from app.logging_setup import app_logger
from app.services.run_log import read_active_pointer, read_run_log_lines, runs_log_path

router = APIRouter(tags=["chat-runs"], dependencies=[Depends(require_auth)])
logger = app_logger("runs_router")

# 5 MB cap — well above any realistic turn (~25k events at 200B each).
# Exceeding this returns 413 so the SPA falls back to the persisted
# transcript via ``GET /messages`` instead of the resume stream.
_LOG_SIZE_LIMIT_BYTES = 5 * 1024 * 1024


def _get_vfs(request: Request):
    """Pull the kaos-core VFS off ``app.state.kaos_runtime``.

    Matches the access pattern used elsewhere in the chat router. A
    501 (not 500) surfaces the missing-runtime case as a deployment
    error rather than an internal bug; in practice ``main.create_app``
    always installs it.
    """
    runtime = getattr(request.app.state, "kaos_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "what": "Run resume requires the kaos runtime.",
                "how_to_fix": (
                    "Check that the FastAPI app was built via ``app.main.create_app`` so "
                    "``app.state.kaos_runtime`` is installed."
                ),
                "alternative_tool": "GET /v1/chat/sessions/{id}/messages",
            },
        )
    return runtime.vfs


@router.get("/sessions/{session_id}/runs/active")
async def get_active_run(session_id: str, request: Request) -> dict | None:
    """Return the active-run pointer or ``null`` when none exists.

    Always 200 so the SPA can branch on ``response === null`` instead
    of distinguishing 404 from "session-has-never-run".
    """
    vfs = _get_vfs(request)
    pointer = await read_active_pointer(vfs=vfs, session_id=session_id)
    return pointer


@router.get("/sessions/{session_id}/runs/{run_id}/events")
async def stream_run_events(
    session_id: str,
    run_id: str,
    request: Request,
    after_seq: int = Query(default=-1, ge=-1),
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    """Replay the JSONL run log as an SSE stream.

    Wire shape:

    * ``event:`` = the original event name (e.g. ``text_delta``).
    * ``data:`` = the original JSON payload, unchanged.
    * ``id:`` = the integer ``seq`` (so the EventSource client can
      ``Last-Event-ID``-reconnect).

    After every persisted event has been emitted, sends one final
    ``run_resumed_replay_done`` envelope and closes. Stage 1 does
    not tail an in-flight writer; if the run is still ``running``
    when the resume client connects, the SPA shows whatever's on
    disk and the next attached client picks up new events the next
    time it reconnects.
    """
    vfs = _get_vfs(request)

    # Per EventSource spec, ``Last-Event-ID`` (when present) overrides
    # a manual ``?after_seq=`` query — the browser's auto-reconnect
    # always sends the header. Parse defensively: a malformed header
    # falls back to whatever ``after_seq`` was on the query string.
    effective_after = after_seq
    if last_event_id is not None:
        try:
            effective_after = int(last_event_id)
        except ValueError:
            pass

    events, total_bytes = await read_run_log_lines(
        vfs=vfs,
        session_id=session_id,
        run_id=run_id,
        after_seq=effective_after,
        size_limit_bytes=_LOG_SIZE_LIMIT_BYTES,
    )
    if total_bytes > _LOG_SIZE_LIMIT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "what": f"Run log is {total_bytes} bytes (limit: {_LOG_SIZE_LIMIT_BYTES}).",
                "how_to_fix": (
                    "Fall back to GET /v1/chat/sessions/{id}/messages to read the persisted "
                    "transcript; live resume of oversized runs is not supported."
                ),
                "alternative_tool": "GET /v1/chat/sessions/{session_id}/messages",
            },
        )

    pointer = await read_active_pointer(vfs=vfs, session_id=session_id)
    log_exists = await vfs.exists(runs_log_path(session_id, run_id))
    if not log_exists and (pointer is None or pointer.get("run_id") != run_id):
        # No log on disk AND the active pointer (if any) doesn't claim
        # this run id. Surface as 404 so the SPA can give up on resume
        # and fall back to /messages rather than waiting on an empty
        # stream that never closes.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "what": f"Unknown run id {run_id!r} for session {session_id!r}.",
                "how_to_fix": (
                    "Call GET /v1/chat/sessions/{id}/runs/active to discover the current run, "
                    "or GET /v1/chat/sessions/{id}/messages for the persisted transcript."
                ),
                "alternative_tool": "GET /v1/chat/sessions/{session_id}/runs/active",
            },
        )

    async def event_generator():
        for parsed in events:
            seq = parsed.get("seq")
            event_name = parsed.get("event", "message")
            data = parsed.get("data", {})
            yield {
                "event": str(event_name),
                "data": json.dumps(data),
                "id": str(seq),
            }
        # Stage 1: always terminate after the replay even when the
        # writer is still "running". Stage 2 attaches the in-process
        # bell here to tail live events. The SPA's resume reducer
        # ignores unknown event types so this final frame is safe.
        yield {
            "event": "run_resumed_replay_done",
            "data": json.dumps({"final": True}),
        }

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={"X-Accel-Buffering": "no"},
    )
