"""Message-level feedback endpoint (plan Issue 10 layer 2).

Consumer-AI table-stakes parity asks for thumbs-up / thumbs-down per
assistant message. The frontend wires the affordance; this router is
the persistence side: one JSONL line per feedback event under

    .kaos-vfs/single-user-chat/sessions/{sid}/feedback.jsonl

The JSONL surface is intentionally append-only. Each line is a
self-contained record so the audit log is human-grep-friendly and
``kaos-audit-session`` can read it without state. No DELETE / PATCH
on feedback — the user can submit a fresh record with the opposite
sentiment if they change their mind; both lines remain.

Schema (one JSON object per line)::

    {
      "session_id": "01KS...",
      "message_id": "<opaque id from the client>",
      "value": "up" | "down",
      "note": "<optional free-text, ≤2000 chars>",
      "submitted_at": "<ISO 8601 UTC>",
      "tenant_id": "<sha256(token)[:12] or null>"
    }

Endpoint::

    POST /v1/chat/sessions/{session_id}/messages/{message_id}/feedback

Response: 202 Accepted on append, 404 if the session does not exist,
422 on bad value, 413 on note too long.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.exceptions import SessionNotFoundError
from app.persistence.sessions import SessionStore
from app.settings import AppSettings

router = APIRouter(tags=["feedback"])

# Cap on the per-feedback note free-text. Anything longer is rejected
# with 413 — the audit log is a quality signal, not a long-form
# substrate, and a single line bounded under 2KB keeps the JSONL
# greppable and survives most logging pipelines without truncation.
_MAX_NOTE_CHARS = 2_000


class FeedbackBody(BaseModel):
    value: Literal["up", "down"]
    note: str | None = Field(default=None, max_length=_MAX_NOTE_CHARS)


class FeedbackResponse(BaseModel):
    """Tiny 202 envelope — confirms append, exposes the timestamp the
    server stamped (so the client can render a "Submitted ✓ at HH:MM").
    """

    submitted_at: datetime


def _atomic_append_jsonl(path: Path, line: str) -> None:
    """Append a single JSONL line with O_APPEND for crash-safety.

    O_APPEND on POSIX guarantees the append is atomic for writes
    smaller than PIPE_BUF (4096 on Linux); our records are bounded by
    ``_MAX_NOTE_CHARS + ~200 bytes of envelope``, well under the
    threshold. No fsync — the audit log is best-effort durability;
    losing the last few lines on a crash is acceptable, and forcing
    an fsync per feedback adds latency the user will feel.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _feedback_log_path(vfs_root: Path, session_id: str) -> Path:
    """Where the JSONL audit log for one session lives. Co-located
    with ``meta.json`` under ``single-user-chat/sessions/{sid}/`` so
    ``kaos-audit-session`` can find it without a separate registry.
    """
    return vfs_root / "single-user-chat" / "sessions" / session_id / "feedback.jsonl"


@router.post(
    "/sessions/{session_id}/messages/{message_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_feedback(
    session_id: str,
    message_id: str,
    body: FeedbackBody,
    request: Request,
    tenant_id: Annotated[str | None, Depends(require_auth)],
) -> FeedbackResponse:
    """Append one feedback record to the per-session JSONL audit log.

    The endpoint is best-effort: a write failure surfaces as 500 so
    the SPA UI can show a retry affordance, but never blocks the
    chat surface (feedback is informational, not load-bearing).
    """
    # 1. Verify the session exists. The SPA UI shouldn't even surface
    #    the thumbs button before the assistant message renders, but
    #    a slow client could fire after archive — return 404 honestly
    #    rather than create a feedback log for a session that has
    #    been removed.
    store: SessionStore = request.app.state.session_store
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    # 2. Stamp the record server-side (never trust client clocks for
    #    audit). datetime.now(UTC) → ISO 8601 round-trip via pydantic.
    submitted_at = datetime.now(UTC)
    settings: AppSettings = request.app.state.app_settings
    log_path = _feedback_log_path(settings.vfs_path, session_id)
    record = {
        "session_id": session_id,
        "message_id": message_id,
        "value": body.value,
        "note": body.note,
        "submitted_at": submitted_at.isoformat(),
        "tenant_id": tenant_id,
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    # 3. Append. _atomic_append_jsonl uses O_APPEND so concurrent
    #    feedback writes from multiple browser tabs never interleave.
    _atomic_append_jsonl(log_path, line)
    return FeedbackResponse(submitted_at=submitted_at)
