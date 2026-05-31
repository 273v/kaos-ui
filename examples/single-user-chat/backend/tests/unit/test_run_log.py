"""RunEventLog round-trips against a tmp VFS.

Covers the three lifecycle steps the SSE-resume design depends on:

* ``open`` writes a ``running`` pointer + an empty JSONL log.
* ``append`` adds one JSONL line per event, preserves order, tolerates
  a missing log (recreates), and updates ``last_seq``.
* ``mark_done`` flips the pointer to ``done`` / ``error`` and stamps
  ``completed_at`` + the final ``last_seq``.

The replay helper ``read_run_log_lines`` exercises the ``after_seq``
filter the resume endpoint relies on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _StubRuntime:
    """Minimal `runtime` shim — only ``vfs`` is read by ``RunEventLog``."""

    def __init__(self, vfs: Any) -> None:
        self.vfs = vfs


@pytest.fixture
def vfs(tmp_vfs_path: Path) -> Any:
    from kaos_core.vfs import VFSConfig, VirtualFileSystem
    from kaos_core.vfs.models import IsolationMode

    cfg = VFSConfig(disk_base_path=tmp_vfs_path, isolation_mode=IsolationMode.GLOBAL)
    return VirtualFileSystem(config=cfg)


async def test_open_writes_running_pointer_and_empty_log(vfs: Any) -> None:
    from app.services.run_log import RunEventLog, runs_active_path, runs_log_path

    log = await RunEventLog.open(
        runtime=_StubRuntime(vfs),
        session_id="sess-1",
        run_id="turn-0000-abc",
        model="anthropic:claude-haiku-4-5",
        turn_index=0,
    )
    assert log.run_id == "turn-0000-abc"
    assert log.last_seq == -1

    # Pointer reflects ``running`` + the constructor inputs.
    raw = await vfs.read(runs_active_path("sess-1"))
    pointer = json.loads(raw.decode("utf-8"))
    assert pointer["status"] == "running"
    assert pointer["run_id"] == "turn-0000-abc"
    assert pointer["model"] == "anthropic:claude-haiku-4-5"
    assert pointer["turn_index"] == 0
    assert pointer["completed_at"] is None
    assert pointer["last_seq"] == -1

    # Log file exists and is empty.
    log_raw = await vfs.read(runs_log_path("sess-1", "turn-0000-abc"))
    assert log_raw == b""


async def test_append_preserves_order_and_updates_last_seq(vfs: Any) -> None:
    from app.services.run_log import RunEventLog, read_run_log_lines

    log = await RunEventLog.open(
        runtime=_StubRuntime(vfs),
        session_id="sess-2",
        run_id="turn-0001-def",
        model="openai:gpt-5",
        turn_index=1,
    )

    # Three events; sequences are not monotonic on purpose to confirm
    # we don't sort or coerce — the writer trusts the caller.
    await log.append("text_delta", {"type": "text_delta", "sequence": 0, "content": "hi"}, 0)
    await log.append("text_delta", {"type": "text_delta", "sequence": 1, "content": " "}, 1)
    await log.append("turn_summary", {"type": "turn_summary", "sequence": 5, "text": "hi "}, 5)

    assert log.last_seq == 5

    events, total_bytes = await read_run_log_lines(
        vfs=vfs, session_id="sess-2", run_id="turn-0001-def"
    )
    assert total_bytes > 0
    assert [e["seq"] for e in events] == [0, 1, 5]
    assert events[0]["event"] == "text_delta"
    assert events[-1]["event"] == "turn_summary"
    assert events[0]["data"]["content"] == "hi"

    # ``after_seq`` filters out everything ``<= after_seq``.
    tail, _ = await read_run_log_lines(
        vfs=vfs, session_id="sess-2", run_id="turn-0001-def", after_seq=1
    )
    assert [e["seq"] for e in tail] == [5]


async def test_mark_done_flips_pointer_and_stamps_completed_at(vfs: Any) -> None:
    from app.services.run_log import RunEventLog, read_active_pointer

    log = await RunEventLog.open(
        runtime=_StubRuntime(vfs),
        session_id="sess-3",
        run_id="turn-0002-ghi",
        model="google:gemini-2.5-flash",
        turn_index=2,
    )
    await log.append("text_delta", {"type": "text_delta", "sequence": 0}, 0)
    await log.mark_done(status="done")

    pointer = await read_active_pointer(vfs=vfs, session_id="sess-3")
    assert pointer is not None
    assert pointer["status"] == "done"
    assert pointer["completed_at"] is not None
    assert pointer["last_seq"] == 0
    # ``run_id`` preserved across the status flip so resume clients
    # can still locate the JSONL log after completion.
    assert pointer["run_id"] == "turn-0002-ghi"

    # Repeated calls (``error`` after ``done``) are idempotent — the
    # most recent call wins.
    await log.mark_done(status="error")
    pointer2 = await read_active_pointer(vfs=vfs, session_id="sess-3")
    assert pointer2 is not None
    assert pointer2["status"] == "error"


async def test_mark_done_is_run_scoped_and_does_not_clobber_a_newer_run(vfs: Any) -> None:
    """Turn-lifecycle redesign: ``mark_done`` must only flip the pointer
    when it still refers to THIS run.

    Because the stream lock is released at stream-end (not after persist),
    the NEXT turn can open its run — overwriting ``active.json`` with its
    own ``run_id`` + ``status="running"`` — BEFORE the prior turn's
    persist BackgroundTask reaches ``mark_done``. An unconditional flip
    would clobber the newer run's "running" pointer back to "done" and
    make the SPA's resume poll miss the live run.
    """
    from app.services.run_log import RunEventLog, read_active_pointer

    sid = "sess-runscoped"
    # Turn N opens.
    log_n = await RunEventLog.open(
        runtime=_StubRuntime(vfs),
        session_id=sid,
        run_id="turn-0000-aaa",
        model="anthropic:claude-haiku-4-5",
        turn_index=0,
    )
    # Turn N+1 opens (allowed now — N's stream lock was already freed),
    # overwriting the active pointer to itself, status=running.
    log_n1 = await RunEventLog.open(
        runtime=_StubRuntime(vfs),
        session_id=sid,
        run_id="turn-0001-bbb",
        model="anthropic:claude-haiku-4-5",
        turn_index=1,
    )

    # Turn N's late persist task marks itself done — must be a NO-OP on
    # the pointer (which now belongs to the running turn N+1).
    await log_n.mark_done(status="done")
    pointer = await read_active_pointer(vfs=vfs, session_id=sid)
    assert pointer is not None
    assert pointer["run_id"] == "turn-0001-bbb"
    assert pointer["status"] == "running", "draining turn N clobbered turn N+1's pointer"

    # Turn N+1 marking itself done DOES flip — it owns the pointer.
    await log_n1.mark_done(status="done")
    pointer2 = await read_active_pointer(vfs=vfs, session_id=sid)
    assert pointer2 is not None
    assert pointer2["run_id"] == "turn-0001-bbb"
    assert pointer2["status"] == "done"


async def test_read_active_pointer_returns_none_when_absent(vfs: Any) -> None:
    from app.services.run_log import read_active_pointer

    pointer = await read_active_pointer(vfs=vfs, session_id="never-opened")
    assert pointer is None
