"""StateSnapshot writer — plan §Issue 5.

Plan acceptance row "State snapshot per turn":

    runs/turn-NNNN/snapshot.json written; replay tool can resume from it

The canonical kaos-agents ``StateSnapshot`` value type
(:class:`kaos_agents.governance.snapshot.StateSnapshot`) captures a
full :class:`TurnInvocation`. The SPA's chat router doesn't have a
TurnInvocation in hand at the canonical-turn boundary — only the
``recorder.records()`` materialized tool-call sidecar plus the
per-turn cost/token totals. This module writes a compact
``snapshot.json`` document with that subset.

When the SPA grows a wired TurnInvocation accumulator (Phase 6+ per
the kaos-agents governance roadmap), this writer can swap to
``StateSnapshot.from_invocation`` + ``to_json`` without changing
the file path or the consumer-visible schema.

Schema (v1):
    {
        "snapshot_version": 1,
        "session_id": str,
        "turn_index": int,
        "run_id": str,
        "model": str,
        "tenant_id": str | None,
        "captured_at": ISO-8601 UTC,
        "build_sha": str | None,
        "tool_calls": [
            {
                "tool_name": str,
                "is_error": bool,
                "duration_ms": float | None,
                "cost_usd": float | None,
                "started_at": float | None,
            },
            ...
        ],
        "totals": {
            "cost_usd": float,
            "tokens": int,
            "tool_call_count": int,
            "tool_error_count": int,
        }
    }
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from kaos_core.logging import get_logger

logger = get_logger("kaos.app.chat.state_snapshot")

SNAPSHOT_VERSION = 1


def turn_snapshot_path(session_id: str, turn_index: int) -> str:
    """Per-turn snapshot path inside the session's VFS namespace.

    Aligns with the tool-call sidecar layout
    (``runs/turn-NNNN.jsonl``) so an auditor opening the runs/
    directory finds both files together.
    """
    return f"runs/turn-{turn_index:04d}/snapshot.json"


def _record_to_dict(record: Any) -> dict[str, Any]:
    """Extract the audit-relevant fields from a ToolCallRecord.

    Typed as ``Any`` because we use ``getattr`` for resilience to
    schema drift in the upstream ``ToolCallRecord`` dataclass — pinning
    a tight type here would force every test or stub to inherit from
    that class for no semantic benefit.
    """
    out: dict[str, Any] = {
        "tool_name": getattr(record, "tool_name", "") or "",
        "is_error": bool(getattr(record, "is_error", False)),
    }
    # Optional fields — historical records may not carry them.
    for opt in ("duration_ms", "cost_usd", "started_at"):
        value = getattr(record, opt, None)
        if value is not None:
            out[opt] = value
    return out


def build_snapshot_payload(
    *,
    session_id: str,
    turn_index: int,
    run_id: str,
    model: str,
    tenant_id: str | None,
    build_sha: str | None,
    sidecar_records: Iterable[Any],
    turn_cost_usd: float,
    turn_tokens: int,
) -> dict[str, Any]:
    """Construct the snapshot payload dict.

    Pure function: easy to unit-test without spinning up a VFS.
    """
    tool_calls = [_record_to_dict(r) for r in sidecar_records]
    error_count = sum(1 for r in tool_calls if r["is_error"])
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "session_id": session_id,
        "turn_index": turn_index,
        "run_id": run_id,
        "model": model,
        "tenant_id": tenant_id,
        "captured_at": datetime.now(UTC).isoformat(),
        "build_sha": build_sha,
        "tool_calls": tool_calls,
        "totals": {
            "cost_usd": float(turn_cost_usd),
            "tokens": int(turn_tokens),
            "tool_call_count": len(tool_calls),
            "tool_error_count": error_count,
        },
    }


async def write_turn_snapshot(
    *,
    runtime: Any,
    session_id: str,
    turn_index: int,
    run_id: str,
    model: str,
    tenant_id: str | None,
    build_sha: str | None,
    sidecar_records: list[Any],
    turn_cost_usd: float,
    turn_tokens: int,
) -> str | None:
    """Write the per-turn snapshot.json to the session VFS.

    Returns the path written on success, ``None`` on failure. Failure
    here is best-effort: a snapshot-write hiccup never breaks the
    real turn-completion BackgroundTask the way a sidecar write does
    (the sidecar is the source of truth; snapshot is its summary).
    """
    if runtime is None:
        return None
    try:
        payload = build_snapshot_payload(
            session_id=session_id,
            turn_index=turn_index,
            run_id=run_id,
            model=model,
            tenant_id=tenant_id,
            build_sha=build_sha,
            sidecar_records=sidecar_records,
            turn_cost_usd=turn_cost_usd,
            turn_tokens=turn_tokens,
        )
        target = turn_snapshot_path(session_id, turn_index)
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await runtime.vfs.write(target, blob)
        return target
    except Exception:
        logger.exception("write_turn_snapshot failed session=%s turn=%d", session_id, turn_index)
        return None


__all__ = [
    "SNAPSHOT_VERSION",
    "build_snapshot_payload",
    "turn_snapshot_path",
    "write_turn_snapshot",
]
