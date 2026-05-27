"""Replay endpoint — re-stream a persisted run's event log (plan Issue 6).

Court-reproducibility blocker: an attorney looking at yesterday's
turn needs to see *exactly* the events the model saw, in order, with
no live LLM cost. The SPA already persists every run's event stream
to

    .kaos-vfs/single-user-chat/sessions/{sid}/runs/turn-NNNN-XXXXXX.jsonl

This router exposes those files over SSE so the existing run-event
consumer in the frontend can replay a trace turn-by-turn without
re-paying inference cost.

Endpoint::

    GET /v1/admin/sessions/{session_id}/replay
        ?turn=N       (optional — replay only this turn index)
        &delay_ms=N   (optional — paced replay for SSE-client testing)

Response: ``text/event-stream`` with one ``data: <line>\\n\\n`` chunk
per persisted JSONL line, in original order, followed by a terminal
``event: replay_complete`` frame.

Security: tenant-scoped via ``require_auth``. Only the tenant that
owns a session can replay it. No write side-effects — this is pure
read-only re-streaming of an already-persisted artifact.

Why a separate ``/admin/`` prefix:
    Court-reproducibility / postmortem traffic is operator tooling;
    keeping it off the per-tenant ``/v1/chat/`` prefix prevents
    accidental client-side coupling (a replay is NOT a run).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse

from app.auth import require_auth
from app.exceptions import SessionNotFoundError
from app.persistence.sessions import SessionStore
from app.settings import AppSettings

router = APIRouter(tags=["replay"])


def _runs_dir(vfs_root: Path, session_id: str) -> Path:
    return vfs_root / "single-user-chat" / "sessions" / session_id / "runs"


def _turn_files(runs_dir: Path, turn: int | None) -> list[Path]:
    """Return the persisted turn jsonl files, optionally filtered to one turn.

    Filenames follow ``turn-NNNN-XXXXXX.jsonl`` so a lexical sort is
    also a chronological sort. When ``turn`` is given, returns only
    files whose ``NNNN`` segment matches that integer.
    """
    if not runs_dir.is_dir():
        return []
    files = sorted(p for p in runs_dir.iterdir() if p.name.startswith("turn-"))
    if turn is None:
        return files
    needle = f"turn-{turn:04d}-"
    return [p for p in files if p.name.startswith(needle)]


@router.get(
    "/sessions/{session_id}/replay",
    response_class=EventSourceResponse,
)
async def replay_session(
    session_id: str,
    request: Request,
    tenant_id: Annotated[str | None, Depends(require_auth)],
    turn: int | None = Query(
        default=None,
        ge=0,
        description="Replay only this 0-based turn index. Omit for full session.",
    ),
    delay_ms: int = Query(
        default=0,
        ge=0,
        le=5_000,
        description="Artificial inter-event delay in milliseconds (0=fastest).",
    ),
) -> EventSourceResponse:
    """Stream a session's persisted run events back over SSE.

    Side-effect free. Pure read of the on-disk JSONL files. Raises
    404 if the session does not exist for this tenant, or 404 if the
    requested turn index isn't present.
    """
    # 1. Tenant-scoped session lookup — refuse cross-tenant replays.
    store: SessionStore = request.app.state.session_store
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # 2. Resolve persisted files.
    settings: AppSettings = request.app.state.app_settings
    runs_dir = _runs_dir(settings.vfs_path, session_id)
    files = _turn_files(runs_dir, turn)
    if not files:
        detail = f"No persisted run events for session {session_id!r}" + (
            f" at turn {turn}" if turn is not None else ""
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    delay_seconds = delay_ms / 1000.0

    async def generator() -> asyncio.AsyncIterator[dict[str, str]]:
        # Header: tell the client what's about to flow so it can render
        # a banner / progress bar without parsing every line first.
        yield {
            "event": "replay_started",
            "data": json.dumps(
                {
                    "session_id": session_id,
                    "turn": turn,
                    "file_count": len(files),
                },
                separators=(",", ":"),
            ),
        }
        # EventSourceResponse handles client-disconnect detection at
        # the transport layer (it cancels the generator task). We
        # avoid request.is_disconnected() inside the generator because
        # that primitive binds to the surrounding event loop on first
        # access, which trips up TestClient when each test spins up
        # its own loop.
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                # File was rotated or moved mid-replay. Skip with a
                # warning event so the operator sees the gap rather
                # than getting a silently truncated trace.
                yield {
                    "event": "replay_warning",
                    "data": json.dumps(
                        {"missing_file": f.name},
                        separators=(",", ":"),
                    ),
                }
                continue
            for raw in text.splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                # Pass the line through unchanged. The SPA's existing
                # SSE consumer already knows how to parse the SPA's
                # own event envelope, and the persisted file is in
                # exactly that envelope shape.
                yield {"event": "replay_event", "data": raw}
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
        yield {
            "event": "replay_complete",
            "data": json.dumps(
                {"session_id": session_id, "file_count": len(files)},
                separators=(",", ":"),
            ),
        }

    return EventSourceResponse(generator())
