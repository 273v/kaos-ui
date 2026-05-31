"""Unit tests for ``app/services/locks.py`` — B1.2 per-session asyncio.Lock."""

from __future__ import annotations

import asyncio

import pytest

from app.services.locks import (
    get_session_lock,
    get_session_persist_lock,
    is_session_running,
    session_lock,
)


@pytest.mark.unit
def test_get_session_lock_returns_singleton_per_session_id() -> None:
    lock_a = get_session_lock("session-A")
    lock_a_again = get_session_lock("session-A")
    lock_b = get_session_lock("session-B")
    assert lock_a is lock_a_again
    assert lock_a is not lock_b


@pytest.mark.unit
def test_is_session_running_false_when_no_lock_created() -> None:
    assert is_session_running("never-touched-session") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_session_running_flips_with_acquire_release() -> None:
    sid = "flip-flop-session"
    assert is_session_running(sid) is False
    async with session_lock(sid):
        assert is_session_running(sid) is True
    assert is_session_running(sid) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_acquires_serialize() -> None:
    """Two coroutines acquiring the same session lock must serialize —
    the second only proceeds after the first releases. This is the
    contract that protects against the same-process race the SPA's
    ``runs/active.json`` soft-check cannot.
    """
    sid = "serialize-session"
    order: list[str] = []

    async def worker(name: str, delay: float) -> None:
        async with session_lock(sid):
            order.append(f"{name}-enter")
            await asyncio.sleep(delay)
            order.append(f"{name}-exit")

    # First worker holds the lock for 50ms; second worker must wait.
    await asyncio.gather(
        worker("first", 0.05),
        worker("second", 0.0),
    )

    assert order == ["first-enter", "first-exit", "second-enter", "second-exit"], order


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_lock_release_on_exception() -> None:
    """Lock must release even when the body raises — required so that a
    failed POST doesn't permanently wedge a session.
    """
    sid = "exception-session"

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        async with session_lock(sid):
            raise _Boom()

    assert is_session_running(sid) is False


# --- Turn-lifecycle redesign (2026-05-31): stream lock vs persist lock ---


@pytest.mark.unit
def test_persist_lock_is_distinct_from_stream_lock() -> None:
    """The persist lock must be a SEPARATE object from the stream lock —
    they protect different phases (the stream vs the post-stream persist)
    and must be independently held/released.
    """
    sid = "two-locks-session"
    assert get_session_persist_lock(sid) is not get_session_lock(sid)
    # ...but each is a stable singleton per session.
    assert get_session_persist_lock(sid) is get_session_persist_lock(sid)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_is_free_for_next_turn_while_persist_still_running() -> None:
    """The core invariant of the follow-up-send fix.

    Models the redesigned lifecycle:
      1. A turn streams        → stream lock held; session is "running".
      2. Stream ends           → the generator's ``finally`` releases the
                                  STREAM lock (synchronously), while the
                                  post-stream ``_do_persist`` task holds
                                  the PERSIST lock.
      3. "Draining" window     → persist is still running, but the stream
                                  lock is free.

    A follow-up POST gates on ``is_session_running`` (the stream lock).
    Pre-fix, the stream lock was released only AFTER persist, so a
    follow-up in the draining window 409'd ~50% of the time. Post-fix,
    ``is_session_running`` reports the session FREE during draining, so
    the follow-up is accepted — no 409.
    """
    sid = "draining-session"
    stream_lock = get_session_lock(sid)
    persist_lock = get_session_persist_lock(sid)

    # 1. Streaming.
    await stream_lock.acquire()
    assert is_session_running(sid) is True

    # 2. _do_persist starts (persist lock), then the generator releases
    #    the stream lock at stream-end.
    await persist_lock.acquire()
    stream_lock.release()

    # 3. Draining: persist still running, but the session is FREE for the
    #    next turn. This is the assertion the bug violated.
    assert is_session_running(sid) is False
    assert persist_lock.locked() is True

    persist_lock.release()
    assert is_session_running(sid) is False
