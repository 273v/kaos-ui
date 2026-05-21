"""Turn-completion persistence as a Starlette BackgroundTask.

The SPA's chat router used to await its post-stream writes
(heuristic-title patch, message-count touch, tool-call sidecar
serialization, and the LLM auto-titler) inside the SSE event
generator's ``finally:`` block. That coupled durable state to the
client's connection lifetime: when the React app navigated away
seconds after a turn finished (the natural "click New chat" flow),
the SSE generator was closed, the ``finally:`` block's ``await``
statements got cancelled, and the writes were silently lost. The
2026-05-18 persona matrix found 8/10 sessions stuck at ``Untitled``
with ``message_count=0`` for exactly this reason.

The fix moves the writes from a finally-block ``await`` to a
Starlette :class:`~starlette.background.BackgroundTask` attached to
the SSE response. The framework guarantees the BackgroundTask runs
after the response body has been fully sent and is decoupled from
the request scope, so client-disconnect cancellation can't kill it.
The SSE generator's ``finally:`` block now only snapshots the
``recorder.records()`` state into a shared container the
BackgroundTask reads; the actual writes — sidecar persistence,
heuristic title, message-count touch, LLM auto-titler — all happen
in :func:`persist_turn_completion` running on the framework's
post-response timeline.

See ``kaos-modules/docs/plans/persona-matrix-followups.md`` §7 and
filed task UX-D1.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from kaos_core.logging import get_logger

from app.exceptions import SessionNotFoundError
from app.models import HistoryMessage
from app.persistence.sessions import SessionStore
from app.services.title import maybe_retitle_session
from app.services.tool_call_recorder import (
    ToolCallRecord,
    serialize_records,
    turn_sidecar_path,
)

logger = get_logger("kaos.app.chat.persist_turn")


def _derive_title(first_message: str, *, max_len: int = 60) -> str:
    """Heuristic title from the first user message.

    Mirrors the inline helper that used to live in the chat router so
    callers of this module don't need to import the route.
    """
    text = " ".join(first_message.split())
    if not text:
        return "Untitled"
    if len(text) <= max_len:
        return text
    cutoff = text.rfind(" ", 0, max_len)
    if cutoff <= 0:
        cutoff = max_len
    return text[:cutoff].rstrip() + "…"


async def persist_turn_completion(
    *,
    store: SessionStore,
    session_id: str,
    is_first_turn: bool,
    user_message: str,
    sidecar_records: list[ToolCallRecord],
    runtime: Any | None,
    turn_index: int,
    fetch_history: Callable[[str], Awaitable[list[HistoryMessage]]],
    turn_cost_usd: float = 0.0,
    turn_tokens: int = 0,
    tenant_id: str | None = None,
) -> None:
    """Run every post-turn durable side effect as a detached task.

    Order is deliberate:

    1. **Tool-call sidecar** persists first so a downstream failure
       (e.g. LLM-titler crash) never costs the agent its tool trace.
       Records are taken by snapshot — the caller MUST pass a fully
       materialized list before scheduling the task; the recorder
       instance itself isn't safe to share once the generator exits.
    2. **Heuristic title** (on first turn only) and **message-count
       touch** are issued together so the sidebar gets a meaningful
       label and the right message count on the very next refresh.
       A failure here is logged; we still proceed to the LLM titler.
    3. **LLM auto-titler** runs last. It re-reads kaos-agents memory
       via ``fetch_history`` to compose a polished title and replaces
       the heuristic one. Failures here are best-effort — the
       heuristic title already shipped, so the user sees something
       useful regardless.

    All three steps are inside a single ``try / except`` so an early
    failure can't take down later ones, and ``SessionNotFoundError``
    is treated as a quiet race against archive/delete (the session
    really is gone — no point retrying).
    """
    # Step 1: tool-call sidecar.
    if sidecar_records and runtime is not None:
        try:
            blob = serialize_records(sidecar_records)
            await runtime.vfs.write(turn_sidecar_path(session_id, turn_index), blob)
        except SessionNotFoundError:
            return
        except Exception:
            logger.exception(
                "failed to persist tool-call sidecar session=%s turn=%d",
                session_id,
                turn_index,
            )

    # Step 2: heuristic title + message-count touch + cost/token rollup.
    #
    # Cost telemetry (P1-3 / UX-A4 #342): we receive the per-turn
    # cost+tokens from the SSE-stream recorder. ``last_turn_*`` are
    # set verbatim; ``total_*`` accumulate by reading the prior
    # SessionMeta and adding the turn delta. None → 0 + delta when
    # the session predates this fix.
    try:
        meta_before = await store.get(session_id, tenant_id=tenant_id)
        prior_total_cost = meta_before.total_cost_usd or 0.0
        prior_total_tokens = meta_before.total_tokens or 0
        patch_kwargs: dict[str, Any] = {
            "last_turn_cost_usd": turn_cost_usd,
            "last_turn_tokens": turn_tokens,
            "total_cost_usd": prior_total_cost + turn_cost_usd,
            "total_tokens": prior_total_tokens + turn_tokens,
        }
        if is_first_turn:
            patch_kwargs["title"] = _derive_title(user_message)
            patch_kwargs["title_source"] = "auto"
        await store.patch(session_id, tenant_id=tenant_id, **patch_kwargs)
        await store.touch(session_id, increment_messages=2, tenant_id=tenant_id)
    except SessionNotFoundError:
        return
    except Exception:
        logger.exception("persist_turn_completion: failed touch session=%s", session_id)

    # Step 3: LLM auto-titler (best-effort polish).
    try:
        await maybe_retitle_session(
            store=store,
            session_id=session_id,
            fetch_history=fetch_history,
            tenant_id=tenant_id,
        )
    except SessionNotFoundError:
        return
    except Exception:
        logger.exception(
            "persist_turn_completion: title summarize failed session=%s",
            session_id,
        )
