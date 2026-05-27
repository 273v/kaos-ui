"""Message-level rewind primitives (plan Issue 10 L3 + L4).

Consumer-AI table-stakes parity asks for two distinct affordances:

* **Regenerate** (L3) — click on an assistant message → that message
  + everything after it disappears + the SPA reruns the user turn
  that preceded it.
* **Edit-prior** (L4) — click on a user message → inline editor →
  save → the edited user message stays, everything after it
  disappears + the SPA reruns the now-edited user turn.

Both affordances reduce to the same server-side primitive:

    truncate the SessionMemory MESSAGES section at index N

The actual *rerun* is the client's responsibility — it POSTs the
prior user message back to ``/v1/chat/sessions/{sid}/messages``
exactly like a fresh send. Keeping rewind separate from rerun:

1. Lets the client preview the truncated transcript before committing
   to spend the LLM cost.
2. Keeps the server endpoint side-effect-bounded to file I/O — no
   LLM kick-off inside the route.
3. Mirrors the ChatGPT / Claude.ai UX where Regenerate visually pops
   the message off, then streams a fresh one back.

Endpoints (mounted under ``/v1/chat`` for tenant-auth parity)::

    POST  /sessions/{sid}/messages/{idx}/regenerate
    PATCH /sessions/{sid}/messages/{idx}

Both are tenant-scoped via ``require_auth`` and 404 on cross-tenant
session ids. Both 422 on a request that would rewind across an
invariant (e.g., edit a non-user message; regenerate at idx 0).
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status

# Re-exported from kaos-agents to keep the on-disk path encoding in
# lockstep with how the agent runtime resolves SessionMemory paths.
from kaos_agents.api.settings import scope_session_id
from pydantic import BaseModel, Field

from app.auth import require_auth
from app.exceptions import SessionNotFoundError
from app.persistence.sessions import SessionStore
from app.services.locks import get_session_lock
from app.settings import AppSettings

# kaos-agents' memory.store URL-percent-encodes the scoped session id
# so the directory survives Windows (where ``:`` is a reserved char in
# the alternate-data-stream filesystem). Mirror its quoting exactly so
# the SPA reads the same file the agent writes. The safe-set matches
# ``kaos_agents.memory.store._SAFE_PATH_CHARS`` — keep them in sync if
# either side changes.
_VFS_COMPONENT_SAFE_CHARS = "-_.~"

router = APIRouter(tags=["messages"])


class RewindResponse(BaseModel):
    """Tiny envelope confirming a rewind operation.

    The frontend uses ``item_count`` to render the truncated
    transcript immediately, then issues a fresh send to trigger the
    new run. ``rewound_role`` is a sanity-check so the client never
    rewinds a user message thinking it was the assistant.
    """

    session_id: str
    item_count: int
    rewound_role: Literal["user", "assistant", "system"]


class EditPriorBody(BaseModel):
    content: str = Field(min_length=1, max_length=64_000)


def _memory_path(vfs_root: Path, session_id: str, tenant_id: str | None) -> Path:
    """Locate the SessionMemory JSON for a tenant-scoped session.

    The on-disk encoding mirrors kaos-agents' ``_safe_component`` —
    URL-percent-encode the scoped component so the directory survives
    Windows (where ``:`` is reserved). On Linux/macOS this turns the
    scoped id ``tenant:sid`` into the directory ``tenant%3Asid``.
    The SPA reads the same file the agent runtime writes — there's
    no second copy to keep in sync.
    """
    scoped = scope_session_id(session_id, tenant_id)
    encoded = urllib.parse.quote(scoped, safe=_VFS_COMPONENT_SAFE_CHARS)
    return vfs_root / "kaos-agents" / "sessions" / encoded / "memory.json"


def _load_memory(path: Path) -> dict:
    """Read the memory snapshot. Raises 404 if missing — the route
    handler maps that to the right HTTP status."""
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_memory(path: Path, payload: dict) -> None:
    """Write the memory snapshot via os.replace so a crash mid-write
    can never leave a half-rewritten file. The temp file is colocated
    with the target so the replace is on the same filesystem.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def _items_section(memory: dict) -> list[dict]:
    """Resolve the MESSAGES section's items list — empty if absent."""
    sections = memory.get("sections", {})
    messages = sections.get("messages", {})
    return list(messages.get("items", []))


def _role_of(item: dict) -> Literal["user", "assistant", "system"]:
    """SessionMemory items prefix the role into ``content`` as
    ``"user: ..."``, ``"assistant: ..."``, or ``"system: ..."``.
    Default to ``"assistant"`` for malformed lines so the rewind
    proceeds gracefully (the role is informational, not load-bearing).
    """
    text = item.get("content", "")
    if text.startswith("user: "):
        return "user"
    if text.startswith("system: "):
        return "system"
    return "assistant"


def _set_items(memory: dict, items: list[dict]) -> dict:
    """Return a shallow-copied memory dict with the messages items
    replaced. The non-messages sections (plan_examples, documents,
    actions, …) are preserved verbatim — rewind only touches the
    user-facing transcript.
    """
    sections = dict(memory.get("sections", {}))
    messages = dict(sections.get("messages", {}))
    messages["items"] = items
    sections["messages"] = messages
    out = dict(memory)
    out["sections"] = sections
    return out


async def _assert_session_owned(
    store: SessionStore, session_id: str, tenant_id: str | None
) -> None:
    """Tenant-scoped 404 for cross-tenant access (mirrors B0.1).

    Centralizes the SessionNotFoundError → 404 mapping so both
    endpoints share the same precondition.
    """
    try:
        await store.get(session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/messages/{idx}/regenerate",
    response_model=RewindResponse,
)
async def regenerate_from(
    session_id: str,
    idx: int,
    request: Request,
    tenant_id: Annotated[str | None, Depends(require_auth)],
) -> RewindResponse:
    """Truncate the MESSAGES section at index ``idx`` (inclusive).

    Spec: ``idx`` must point to an assistant message — that message
    and every item after it are dropped. The prior user message
    stays; the client reissues it via POST /messages to trigger a
    fresh run with full ChatGPT/Claude.ai parity.

    Errors:

    - 404 if the session isn't owned by this tenant.
    - 404 if the session has no persisted memory yet (no turns).
    - 422 if ``idx`` is out of range or doesn't point to an assistant.
    """
    store: SessionStore = request.app.state.session_store
    settings: AppSettings = request.app.state.app_settings
    await _assert_session_owned(store, session_id, tenant_id)

    # Per-session async lock — concurrent regenerates from two tabs
    # would otherwise race the load-modify-store cycle and leave a
    # corrupted transcript. The same lock guards normal /chat POSTs
    # (#588), so a regenerate while a send is in flight blocks
    # cleanly instead of trampling.
    async with get_session_lock(session_id):
        path = _memory_path(settings.vfs_path, session_id, tenant_id)
        try:
            memory = _load_memory(path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Session {session_id!r} has no persisted MESSAGES yet. "
                    "Regenerate is only valid after at least one assistant "
                    "turn has completed."
                ),
            ) from exc

        items = _items_section(memory)
        if idx < 0 or idx >= len(items):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"idx={idx} out of range; MESSAGES has {len(items)} items. "
                    "Pass a 0-based index into the messages list returned by "
                    "GET /v1/chat/sessions/{sid}/messages."
                ),
            )
        target_role = _role_of(items[idx])
        if target_role != "assistant":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot regenerate at idx={idx}: that item is a "
                    f"{target_role!r} message, not an assistant message. "
                    "Use PATCH /messages/{idx} to edit user messages."
                ),
            )

        # Keep items strictly before the target — the prior user turn
        # remains so the client can re-send it verbatim.
        kept = items[:idx]
        _atomic_write_memory(path, _set_items(memory, kept))

        # Touch the session so message_count reflects the truncation.
        await store.touch(
            session_id,
            tenant_id=tenant_id,
            increment_messages=-(len(items) - len(kept)),
        )

    return RewindResponse(
        session_id=session_id,
        item_count=len(kept),
        rewound_role=target_role,
    )


@router.patch(
    "/sessions/{session_id}/messages/{idx}",
    response_model=RewindResponse,
)
async def edit_prior(
    session_id: str,
    idx: int,
    body: EditPriorBody,
    request: Request,
    tenant_id: Annotated[str | None, Depends(require_auth)],
) -> RewindResponse:
    """Edit a prior user message in place and truncate forward.

    Spec: ``idx`` must point to a user message. The content at that
    index is replaced; every subsequent item (assistant reply,
    follow-on user turns) is dropped. The client then re-sends the
    edited user message to trigger a fresh run.

    The role prefix (``"user: "``) is preserved automatically; the
    request body carries only the user-authored text.
    """
    store: SessionStore = request.app.state.session_store
    settings: AppSettings = request.app.state.app_settings
    await _assert_session_owned(store, session_id, tenant_id)

    async with get_session_lock(session_id):
        path = _memory_path(settings.vfs_path, session_id, tenant_id)
        try:
            memory = _load_memory(path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id!r} has no persisted MESSAGES yet.",
            ) from exc

        items = _items_section(memory)
        if idx < 0 or idx >= len(items):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"idx={idx} out of range; MESSAGES has {len(items)} items.",
            )
        target_role = _role_of(items[idx])
        if target_role != "user":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot edit at idx={idx}: that item is a {target_role!r} "
                    "message, not a user message. Use POST .../regenerate to "
                    "rewind from an assistant message."
                ),
            )

        # Replace the user message content with the edited text
        # (preserving the ``"user: "`` prefix so the assistant on the
        # next run sees the same conversation shape).
        edited = dict(items[idx])
        edited["content"] = f"user: {body.content}"
        new_items = [*items[:idx], edited]
        _atomic_write_memory(path, _set_items(memory, new_items))

        await store.touch(
            session_id,
            tenant_id=tenant_id,
            increment_messages=-(len(items) - len(new_items)),
        )

    return RewindResponse(
        session_id=session_id,
        item_count=len(new_items),
        rewound_role=target_role,
    )
