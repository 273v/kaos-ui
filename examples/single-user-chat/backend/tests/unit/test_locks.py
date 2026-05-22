"""Unit tests for ``app/services/locks.py`` — B1.2 per-session asyncio.Lock."""

from __future__ import annotations

import asyncio

import pytest

from app.services.locks import (
    get_session_lock,
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
