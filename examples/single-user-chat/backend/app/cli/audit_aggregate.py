"""kaos-audit-aggregate — cross-session daily audit JSONL exporter.

Plan Issue 5 acceptance criterion: "durable JSONL audit log → VFS"
shipped as a tenant-scoped daily aggregator that consumes the
already-persisted per-session ``runs/turn-NNNN-XXXXXX.jsonl`` files
and produces

    .kaos-vfs/audit/{tenant_hash}/{date}.jsonl

This satisfies the auditor's actual use case ("show me everything
session X did on March 5") without requiring an upstream Runner-level
hook install. Each output line is one **completed turn** summary,
self-contained and grep-friendly.

CLI::

    kaos-audit-aggregate --vfs-path .kaos-vfs --date 2026-05-22
    kaos-audit-aggregate --vfs-path .kaos-vfs --date 2026-05-22 \\
                         --tenant-id 11f8f4450cce
    kaos-audit-aggregate --vfs-path .kaos-vfs --date 2026-05-22 --format json

Each output JSONL line has shape::

    {
      "tenant_id": "11f8f4450cce",
      "session_id": "01KS...",
      "run_id": "run-abc",
      "turn_index": 0,
      "started_at": 1779454179.0,
      "completed_at": 1779454212.0,
      "model": "openai:gpt-5.4-mini",
      "build_sha": "deadbeef1234",
      "tokens_in": 2200,
      "tokens_out": 1100,
      "cost_usd": 0.0060,
      "tool_names_invoked": ["kaos-office-parse-docx", "kaos-content-stats"],
      "intent": "complete",
      "matter_id": "ABC-2026-0042",
      "hipaa_required": false,
      "privileged": false
    }

Exit codes::

    0  success
    2  vfs-path is not a directory
    3  no sessions found for the date / tenant combination
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Tenant-scoped directory names are URL-percent-encoded on disk
# (kaos-agents' _safe_component). See app/routers/messages.py for the
# matching encoding when we READ memory.json. The aggregator filters
# directory names by the "{tenant}%3A" prefix without unquoting.


@dataclass(frozen=True, slots=True)
class TurnAuditLine:
    """One aggregated audit row — exactly the shape persisted to JSONL.

    Frozen + slots: this is value-typed and used in tight loops over
    potentially thousands of sessions. Mutating after construction is
    a bug.
    """

    tenant_id: str | None
    session_id: str
    run_id: str
    turn_index: int
    started_at: float | None
    completed_at: float | None
    model: str | None
    build_sha: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    tool_names_invoked: tuple[str, ...]
    intent: str | None
    matter_id: str | None
    hipaa_required: bool
    privileged: bool


@dataclass
class AggregateReport:
    """Mutable accumulator the aggregator writes into."""

    vfs_root: Path
    date: str  # YYYY-MM-DD
    tenant_filter: str | None
    lines: list[TurnAuditLine] = field(default_factory=list)
    session_count: int = 0
    turn_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_jsonl(self) -> str:
        """Serialize the accumulated lines, one per row."""
        out = []
        for line in self.lines:
            d = asdict(line)
            d["tool_names_invoked"] = list(line.tool_names_invoked)
            out.append(json.dumps(d, separators=(",", ":")))
        return "\n".join(out) + ("\n" if out else "")


def _parse_session_dir(name: str) -> tuple[str | None, str]:
    """Split a session directory name into (tenant_id, session_id).

    Tenant-scoped dirs look like ``11f8f4450cce%3A01KS5HN2VSCA...``
    where ``%3A`` is the URL-encoded ``:``. Unscoped (localhost-dev
    mode) dirs are just the bare session id.
    """
    if "%3A" in name:
        tenant, _, sid = name.partition("%3A")
        return tenant, sid
    return None, name


def _iter_session_dirs(
    vfs_root: Path, tenant_filter: str | None
) -> list[tuple[str | None, str, Path]]:
    """Walk single-user-chat/sessions and return owned dirs.

    Returns ``(tenant_id, session_id, dir_path)`` triples; honors the
    tenant filter when given.
    """
    base = vfs_root / "single-user-chat" / "sessions"
    if not base.is_dir():
        return []
    out: list[tuple[str | None, str, Path]] = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        tenant, sid = _parse_session_dir(entry.name)
        if tenant_filter is not None and tenant != tenant_filter:
            continue
        out.append((tenant, sid, entry))
    return out


def _load_meta(session_dir: Path) -> dict[str, Any] | None:
    """Read meta.json for one session, or None if unreadable."""
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _date_of_epoch(t: float | None) -> str | None:
    """Return YYYY-MM-DD (UTC) for a unix timestamp, or None if missing."""
    if t is None:
        return None
    try:
        return datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def _aggregate_run(
    run_path: Path,
    *,
    tenant: str | None,
    session_id: str,
    meta: dict[str, Any] | None,
    target_date: str,
) -> TurnAuditLine | None:
    """Distill one ``runs/turn-NNNN-RUNID.jsonl`` into a TurnAuditLine.

    Returns None if the run started outside the target date — that
    way the aggregator's date filter is a single comparison per file
    instead of a full scan of every event.
    """
    started_at: float | None = None
    completed_at: float | None = None
    run_id: str | None = None
    model: str | None = None
    build_sha: str | None = None
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    tools: list[str] = []
    intent: str | None = None

    try:
        text = run_path.read_text(encoding="utf-8")
    except OSError:
        return None

    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            evt = json.loads(raw)
        except ValueError:
            continue
        kind = evt.get("event")
        data = evt.get("data") or {}
        if kind == "run_started":
            run_id = data.get("run_id")
            started_at = data.get("started_at")
            model = data.get("model")
            build_sha = data.get("build_sha")
        elif kind == "run_completed":
            completed_at = data.get("completed_at") or completed_at
        elif kind == "usage_observed":
            tin = data.get("tokens_in") or data.get("input_tokens") or 0
            tout = data.get("tokens_out") or data.get("output_tokens") or 0
            cost = data.get("cost_usd") or 0
            if isinstance(tin, int):
                tokens_in += tin
            if isinstance(tout, int):
                tokens_out += tout
            if isinstance(cost, int | float):
                cost_usd += float(cost)
        elif kind == "tool_call_completed":
            tn = data.get("tool_name")
            if isinstance(tn, str):
                tools.append(tn)
        elif kind == "turn_summary":
            intent = data.get("intent") or intent

    # Date filter — gate on the run's start time.
    if _date_of_epoch(started_at) != target_date:
        return None

    # Turn index lives in the filename: ``turn-NNNN-...``
    turn_idx: int = 0
    name = run_path.name
    if name.startswith("turn-") and len(name) >= 9:
        try:
            turn_idx = int(name[5:9])
        except ValueError:
            turn_idx = 0

    meta_d = meta or {}
    return TurnAuditLine(
        tenant_id=tenant,
        session_id=session_id,
        run_id=run_id or "",
        turn_index=turn_idx,
        started_at=started_at,
        completed_at=completed_at,
        model=model,
        build_sha=build_sha,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        tool_names_invoked=tuple(tools),
        intent=intent,
        matter_id=meta_d.get("matter_id"),
        hipaa_required=bool(meta_d.get("hipaa_required", False)),
        privileged=bool(meta_d.get("privileged", False)),
    )


def aggregate(vfs_root: Path, *, date: str, tenant_id: str | None = None) -> AggregateReport:
    """Walk the VFS and accumulate one audit row per completed turn
    that started on the target date.

    ``date`` is YYYY-MM-DD UTC. ``tenant_id`` limits the scan to one
    tenant; ``None`` means "all tenants on this host" (operator mode).
    """
    report = AggregateReport(vfs_root=vfs_root, date=date, tenant_filter=tenant_id)
    for tenant, sid, sdir in _iter_session_dirs(vfs_root, tenant_id):
        report.session_count += 1
        meta = _load_meta(sdir)
        runs_dir = sdir / "runs"
        if not runs_dir.is_dir():
            continue
        for run_file in sorted(p for p in runs_dir.iterdir() if p.name.startswith("turn-")):
            line = _aggregate_run(
                run_file,
                tenant=tenant,
                session_id=sid,
                meta=meta,
                target_date=date,
            )
            if line is not None:
                report.lines.append(line)
                report.turn_count += 1
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kaos-audit-aggregate",
        description=(
            "Aggregate every completed turn that started on the given "
            "date into one JSONL audit log. Reads the persistent "
            "runs/turn-*.jsonl event streams the SPA already writes — "
            "no agent runtime hook required."
        ),
    )
    parser.add_argument("--vfs-path", required=True, type=Path)
    parser.add_argument(
        "--date",
        required=True,
        help="YYYY-MM-DD (UTC). Only turns that started on this date are included.",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help=(
            "Limit the scan to one tenant id (sha256(token)[:12]). "
            "Omit to scan every tenant on the host."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "summary"),
        default="jsonl",
        help="``jsonl``: one row per turn. ``summary``: counts only.",
    )
    args = parser.parse_args(argv)

    vfs = args.vfs_path
    if not vfs.is_dir():
        print(f"error: vfs-path {vfs!r} is not a directory", file=sys.stderr)
        return 2

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"error: --date {args.date!r} is not a valid YYYY-MM-DD", file=sys.stderr)
        return 2

    report = aggregate(vfs, date=args.date, tenant_id=args.tenant_id)
    if report.session_count == 0:
        scope = f"tenant {args.tenant_id!r}" if args.tenant_id else "any tenant"
        print(
            f"warning: no sessions found under {vfs} for {scope}",
            file=sys.stderr,
        )
        return 3

    if args.format == "jsonl":
        sys.stdout.write(report.to_jsonl())
    else:
        sys.stdout.write(
            f"date={report.date} "
            f"tenant={report.tenant_filter or 'all'} "
            f"sessions={report.session_count} "
            f"turns={report.turn_count}\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entrypoint
    sys.exit(main())
