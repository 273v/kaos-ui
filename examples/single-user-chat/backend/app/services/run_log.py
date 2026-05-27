"""Durable per-event log for in-flight chat turns (SSE resume — Stage 1).

Each chat turn streams a sequence of kaos-agents `KaosEvent` payloads
to the SPA via SSE. Today those events are ephemeral: when the user
navigates away the SSE stream is cancelled and the in-flight state is
lost. To make "navigate-away-then-back" paint the partial transcript
and resume streaming, we mirror every yielded SSE frame to disk:

* One **JSONL log** per run at
  ``.kaos-vfs/single-user-chat/sessions/{sid}/runs/{run_id}.jsonl``.
  One line per event, written synchronously before the SSE frame is
  flushed to the client.
* One **active-pointer JSON** per session at
  ``.kaos-vfs/single-user-chat/sessions/{sid}/runs/active.json``.
  Tracks the current/most-recent run id, its status, and (eventually)
  the last flushed sequence number.

The kaos-core VFS exposes only ``read`` / ``write`` / ``exists`` (no
``append``). For Stage 1 we read-modify-write the JSONL on every event
— acceptable for the typical ~20-event turn (the design doc explicitly
calls out this trade-off in §4.1). Stage 2 buffers writes and adds an
``append`` shim on the disk backend.

This module owns NO per-process state — every operation reads or
writes the VFS directly. Cross-tab pub/sub and the ``_LiveRun`` dict
are Stage 2.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Literal

from kaos_core.logging import get_logger

if TYPE_CHECKING:
    from kaos_core.vfs import VirtualFileSystem

logger = get_logger("kaos.app.chat.run_log")

# Namespace must match `SessionStore._meta_path`'s ``single-user-chat``
# prefix so a single VFS root holds both sidecar meta and run logs.
_NS = "single-user-chat/sessions"

RunStatus = Literal["running", "done", "error", "interrupted"]


def runs_active_path(session_id: str) -> str:
    """VFS path for the per-session "is anything live?" pointer."""
    return f"{_NS}/{session_id}/runs/active.json"


def runs_log_path(session_id: str, run_id: str) -> str:
    """VFS path for the per-run JSONL event log."""
    return f"{_NS}/{session_id}/runs/{run_id}.jsonl"


class RunEventLog:
    """One instance per in-flight turn.

    Lifecycle:

    1. :meth:`open` — write the initial ``active.json`` pointer
       (``status="running"``) and create the empty JSONL log.
    2. :meth:`append` — once per yielded SSE frame. Read-modify-write
       on the JSONL. Best-effort: a write failure logs a warning and
       returns; the live SSE keeps flowing (live UX wins over recovery
       fidelity per design §4.1).
    3. :meth:`mark_done` — called from the BackgroundTask after
       :func:`persist_turn_completion` finishes. Flips the pointer to
       ``done`` / ``error`` and stamps ``completed_at`` + the final
       observed ``last_seq``.

    None of these methods raise on VFS failure — instances stay usable
    even after a transient write error so the SSE generator never
    crashes on a log hiccup.
    """

    __slots__ = (
        "_last_seq",
        "_log_path",
        "_pointer_path",
        "_run_id",
        "_session_id",
        "_started_at",
        "_vfs",
    )

    def __init__(
        self,
        *,
        vfs: VirtualFileSystem,
        session_id: str,
        run_id: str,
        started_at: float,
    ) -> None:
        self._vfs = vfs
        self._session_id = session_id
        self._run_id = run_id
        self._started_at = started_at
        self._log_path = runs_log_path(session_id, run_id)
        self._pointer_path = runs_active_path(session_id)
        self._last_seq = -1

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def started_at(self) -> float:
        return self._started_at

    @property
    def last_seq(self) -> int:
        return self._last_seq

    @property
    def log_path(self) -> str:
        return self._log_path

    @property
    def pointer_path(self) -> str:
        return self._pointer_path

    @classmethod
    async def open(
        cls,
        *,
        runtime: Any,
        session_id: str,
        run_id: str,
        model: str,
        turn_index: int,
    ) -> RunEventLog:
        """Construct + write the initial pointer + empty log.

        ``runtime`` must expose ``.vfs`` (a kaos-core ``VirtualFileSystem``).
        The chat router pulls the runtime off
        ``request.app.state.kaos_runtime`` — see ``main.py``.
        """
        vfs: VirtualFileSystem = runtime.vfs  # type: ignore[assignment]
        started_at = time.time()
        log = cls(vfs=vfs, session_id=session_id, run_id=run_id, started_at=started_at)

        # Empty JSONL — a 0-byte file means "no events yet, but the run
        # was opened". Resume readers treat missing-file the same way,
        # so this is belt-and-suspenders; we still create it eagerly so
        # the active-pointer never points at a nonexistent log.
        try:
            await vfs.write(log._log_path, b"")
        except Exception:
            logger.warning(
                "run_log.open: failed to create empty log session=%s run=%s",
                session_id,
                run_id,
            )

        pointer = {
            "run_id": run_id,
            "session_id": session_id,
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
            "last_seq": -1,
            "model": model,
            "turn_index": turn_index,
        }
        try:
            await vfs.write(log._pointer_path, json.dumps(pointer).encode("utf-8"))
        except Exception:
            logger.warning(
                "run_log.open: failed to write active pointer session=%s run=%s",
                session_id,
                run_id,
            )
        return log

    async def append(self, event_name: str, payload: dict[str, Any], sequence: int) -> None:
        """Append one event to the JSONL log.

        Read-modify-write: pull the current bytes, append one line,
        write back. O(N) per event. For Stage 1 turns of ~20 events
        this is well under 1 ms; Stage 2 buffers in memory and flushes
        in batches.

        Failure is logged but does NOT propagate — the live SSE stream
        takes priority over log fidelity. A persistent failure produces
        a gap in the replay log; sequence numbers are monotonic so
        downstream consumers can detect and tolerate gaps.
        """
        line = (
            json.dumps(
                {
                    "seq": sequence,
                    "event": event_name,
                    "data": payload,
                    "ts": time.time(),
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        try:
            existing = b""
            if await self._vfs.exists(self._log_path):
                existing = await self._vfs.read(self._log_path)
            await self._vfs.write(self._log_path, existing + line.encode("utf-8"))
            if sequence > self._last_seq:
                self._last_seq = sequence
        except Exception:
            logger.warning(
                "run_log.append: write failed session=%s run=%s seq=%d event=%s",
                self._session_id,
                self._run_id,
                sequence,
                event_name,
            )

    async def mark_done(self, *, status: RunStatus = "done") -> None:
        """Flip the active-pointer status + stamp ``completed_at``.

        Called from the BackgroundTask after the rest of
        ``persist_turn_completion`` finishes. Idempotent — repeated
        calls just rewrite the same fields.
        """
        completed_at = time.time()
        try:
            raw = await self._vfs.read(self._pointer_path)
            current = json.loads(raw.decode("utf-8"))
        except Exception:
            # Pointer was never written (open() failed) or was
            # subsequently deleted. Reconstruct from local state so the
            # SPA still gets a clean terminal pointer.
            current = {
                "run_id": self._run_id,
                "session_id": self._session_id,
                "status": "running",
                "started_at": self._started_at,
                "completed_at": None,
                "last_seq": self._last_seq,
                "model": None,
                "turn_index": None,
            }

        current["status"] = status
        current["completed_at"] = completed_at
        current["last_seq"] = self._last_seq
        try:
            await self._vfs.write(self._pointer_path, json.dumps(current).encode("utf-8"))
        except Exception:
            logger.warning(
                "run_log.mark_done: failed to update pointer session=%s run=%s",
                self._session_id,
                self._run_id,
            )


async def read_active_pointer(*, vfs: VirtualFileSystem, session_id: str) -> dict[str, Any] | None:
    """Return the current ``active.json`` payload or ``None`` if absent.

    Used by ``GET /v1/chat/sessions/{id}/runs/active``. Treats a
    parse error as "no pointer" so the SPA can recover by starting a
    new turn rather than seeing a 500.
    """
    path = runs_active_path(session_id)
    try:
        if not await vfs.exists(path):
            return None
        raw = await vfs.read(path)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        logger.warning("read_active_pointer: malformed pointer session=%s", session_id)
        return None


async def read_run_log_lines(
    *,
    vfs: VirtualFileSystem,
    session_id: str,
    run_id: str,
    after_seq: int = -1,
    size_limit_bytes: int = 5 * 1024 * 1024,
) -> tuple[list[dict[str, Any]], int]:
    """Read JSONL events with ``seq > after_seq``.

    Returns ``(events, total_bytes)``. Caller compares total_bytes to
    the size limit and surfaces a 413 if exceeded. Lines that fail to
    parse are skipped (we'd rather replay 19/20 events than 0).
    """
    path = runs_log_path(session_id, run_id)
    if not await vfs.exists(path):
        return [], 0
    raw = await vfs.read(path)
    total_bytes = len(raw)
    if total_bytes > size_limit_bytes:
        return [], total_bytes
    events: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        seq = parsed.get("seq")
        if not isinstance(seq, int):
            continue
        if seq <= after_seq:
            continue
        events.append(parsed)
    return events, total_bytes
