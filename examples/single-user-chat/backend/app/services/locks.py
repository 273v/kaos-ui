"""Per-session asyncio locks for concurrent-POST protection (B1.2).

The SPA's existing `runs/active.json` check (in `app/routers/chat.py`
around line 459-485) is a *soft* guard against resumes after a process
restart — it tells the second POST "an earlier run is still marked
running, open the resume stream instead of starting a new one."

It does NOT protect against the **same-process race** where two
browser tabs hit `POST /v1/sessions/{sid}/messages` within a few
hundred milliseconds of each other. Both reads of `active.json`
return `None` (no prior run), both proceed, both write to
SessionMemory, both try to open the same `runs/turn-*.jsonl` —
the second one corrupts the first's state.

This module adds a real `asyncio.Lock` keyed by `session_id`. The
contract:

- The first POST for a session acquires the lock and proceeds.
- A concurrent POST sees `lock.locked()` and immediately 409s with
  `error="run_in_progress"` + `how_to_fix` pointing the SPA at the
  resume endpoint (same shape as the existing soft guard).
- The lock is released only after the SSE response body has been
  fully sent (in the `_do_persist` BackgroundTask).

Single-process scope. Multi-process / multi-worker deployments need a
shared Redis lock or similar; that's out of scope for the
single-user-chat reference SPA. See roadmap §B1.2.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# Module-level dict from session_id → asyncio.Lock. Entries are
# created lazily on first POST for a session. Bounded by the number
# of distinct sessions seen over the process lifetime, which is fine
# for the reference SPA (single user, dozens of sessions per day).
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}

# Per-session lock that serializes the post-stream persist work
# (``_do_persist``) across turns. DISTINCT from the stream lock above.
# The turn-lifecycle redesign (2026-05-31) releases the stream lock the
# instant the SSE body finishes, so the session is free for the next
# turn's stream while the prior turn's persist (canonical-turn write +
# title heuristic + meta bump) is still running. This lock keeps those
# persists from interleaving (turn N+1 persisting before turn N). The
# next turn's STREAM never waits on it — only the next turn's persist
# does — so "session free for the next turn" is no longer coupled to
# "prior turn fully persisted" (the root cause of the 409 follow-up bug).
_SESSION_PERSIST_LOCKS: dict[str, asyncio.Lock] = {}


def get_session_lock(session_id: str) -> asyncio.Lock:
    """Return the stream lock for ``session_id``, creating it on first call.

    Held for the lifetime of the SSE stream only (acquired at POST,
    released in the generator's ``finally`` when the body is fully
    sent). A concurrent POST sees ``locked()`` and 409s.

    Safe to call from any coroutine on the same event loop —
    ``dict.setdefault`` is atomic from the perspective of the single
    asyncio event loop (no ``await`` between check and insert).
    """
    return _SESSION_LOCKS.setdefault(session_id, asyncio.Lock())


def get_session_persist_lock(session_id: str) -> asyncio.Lock:
    """Return the persist lock for ``session_id`` (serializes ``_do_persist``).

    Acquired by each turn's BackgroundTask so post-stream persist work
    runs in turn order even though the stream lock is released earlier.
    """
    return _SESSION_PERSIST_LOCKS.setdefault(session_id, asyncio.Lock())


def is_session_running(session_id: str) -> bool:
    """Return True iff a POST is currently being processed for ``session_id``.

    Sync, non-blocking — for use in the early-409 check.
    """
    lock = _SESSION_LOCKS.get(session_id)
    return lock is not None and lock.locked()


@asynccontextmanager
async def session_lock(session_id: str) -> AsyncIterator[None]:
    """Async context manager — acquires the lock for the duration of
    the ``async with`` block. Use ``is_session_running`` first to
    decide whether to enter at all (the SSE handler can't ``async
    with`` because the streaming lifetime extends past the handler
    function — see the manual acquire/release pattern in
    ``chat.py:send_message``).
    """
    lock = get_session_lock(session_id)
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()
