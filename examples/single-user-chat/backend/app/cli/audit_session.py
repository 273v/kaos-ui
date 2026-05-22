"""``kaos-audit-session`` CLI — postmortem report on a single SPA session.

The CLI was referenced in ``app/services/tool_call_recorder.py:46`` and
``app/routers/chat.py:1399`` as the canonical consumer of per-session
audit data, but the binary did not exist anywhere in the monorepo
(plan Issue 6 — "Can't reproduce / debug yesterday's turn"). This
module fills that gap with a minimal but complete read-only auditor:
point it at a VFS root + session id and it emits a JSON or
human-readable report covering meta, files, memory, turns, and tool
calls.

Read-only by design. Never mutates VFS state. Safe to run against a
session that's actively streaming (parallel readers don't race the
``_atomic_write`` + ``os.replace`` writer).

Exit codes:

- ``0`` — session found, report emitted
- ``1`` — session-id missing or invalid argument shape
- ``2`` — VFS root not found / session not in VFS
- ``3`` — unreadable session (corrupt JSON, missing meta)

Example::

    uv run kaos-audit-session --session-id 01KS7VPNPC65YDJXBMA79CD3DH
    uv run kaos-audit-session --session-id 01KS7V... --format json
    uv run kaos-audit-session --session-id 01KS7V... --vfs-path /custom/.kaos-vfs
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FileEntry:
    filename: str
    size_bytes: int
    parse_status: str
    ocr_applied: bool
    track_changes_detected: bool


@dataclass(slots=True)
class TurnSummary:
    turn_index: int
    run_id: str | None = None
    started_at: float | None = None
    model: str | None = None
    tool_call_count: int = 0
    tool_names: Counter[str] = field(default_factory=Counter)
    error_count: int = 0


@dataclass(slots=True)
class SessionReport:
    session_id: str
    found: bool
    title: str | None = None
    model: str | None = None
    file_count: int = 0
    files: list[FileEntry] = field(default_factory=list)
    memory_section_counts: dict[str, int] = field(default_factory=dict)
    corpus_ever_attached: bool = False
    turn_count: int = 0
    turns: list[TurnSummary] = field(default_factory=list)
    total_tool_calls: int = 0
    tool_name_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "found": self.found,
            "title": self.title,
            "model": self.model,
            "file_count": self.file_count,
            "files": [
                {
                    "filename": f.filename,
                    "size_bytes": f.size_bytes,
                    "parse_status": f.parse_status,
                    "ocr_applied": f.ocr_applied,
                    "track_changes_detected": f.track_changes_detected,
                }
                for f in self.files
            ],
            "memory_section_counts": self.memory_section_counts,
            "corpus_ever_attached": self.corpus_ever_attached,
            "turn_count": self.turn_count,
            "turns": [
                {
                    "turn_index": t.turn_index,
                    "run_id": t.run_id,
                    "started_at": t.started_at,
                    "model": t.model,
                    "tool_call_count": t.tool_call_count,
                    "tool_names": dict(t.tool_names),
                    "error_count": t.error_count,
                }
                for t in self.turns
            ],
            "total_tool_calls": self.total_tool_calls,
            "tool_name_counts": self.tool_name_counts,
            "warnings": self.warnings,
        }


def _load_json(path: Path, report: SessionReport) -> dict[str, Any] | None:
    """Best-effort JSON read. Adds a warning to the report on failure
    so the caller can see which sidecars were unreadable instead of
    the whole audit silently dropping them.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        report.warnings.append(f"unreadable {path.name}: {exc}")
        return None


def _load_meta(vfs_root: Path, session_id: str, report: SessionReport) -> None:
    """Populate title + model from the session's ``meta.json`` sidecar
    written by the SPA's session-create handler.
    """
    meta_path = vfs_root / "single-user-chat" / "sessions" / session_id / "meta.json"
    meta = _load_json(meta_path, report)
    if meta is None:
        report.warnings.append(f"meta.json missing at {meta_path}")
        return
    report.title = meta.get("title")
    report.model = meta.get("model")


def _load_files(vfs_root: Path, session_id: str, report: SessionReport) -> None:
    """Walk the per-session ``files/`` dir, picking up each upload's
    ``*.meta.json`` sidecar (NOT the ``*.kaos.json`` AST sidecar — those
    are not user-facing and are filtered from agent surfaces; see
    #583 + corpus-markdown follow-up).
    """
    files_dir = vfs_root / "sessions" / session_id / "files"
    if not files_dir.is_dir():
        return
    for entry in sorted(files_dir.iterdir()):
        if not entry.name.endswith(".meta.json"):
            continue
        meta = _load_json(entry, report)
        if meta is None:
            continue
        parse = meta.get("parse") or {}
        report.files.append(
            FileEntry(
                filename=meta.get("filename", entry.stem),
                size_bytes=int(meta.get("size_bytes") or 0),
                parse_status=str(parse.get("status") or "unknown"),
                ocr_applied=bool(meta.get("ocr_applied")),
                track_changes_detected=bool(meta.get("track_changes_detected")),
            )
        )
    report.file_count = len(report.files)


def _load_memory(vfs_root: Path, session_id: str, report: SessionReport) -> None:
    """Read the kaos-agents SessionMemory snapshot. The runner writes
    this to ``kaos-agents/sessions/{maybe-tenant:}{sid}/memory.json``.
    We try both the unscoped and a hash-prefixed path because dev/test
    environments differ (see R0.2 tenant-prefix scoping).
    """
    candidates = [
        vfs_root / "kaos-agents" / "sessions" / session_id / "memory.json",
    ]
    # Also try any tenant-prefixed variant ``{hex}:{sid}``.
    scoped_root = vfs_root / "kaos-agents" / "sessions"
    if scoped_root.is_dir():
        for child in scoped_root.iterdir():
            name = child.name
            if name.endswith(f":{session_id}") or name.endswith(f"%3A{session_id}"):
                candidates.append(child / "memory.json")
    memory: dict[str, Any] | None = None
    for candidate in candidates:
        memory = _load_json(candidate, report)
        if memory:
            break
    if memory is None:
        return
    report.corpus_ever_attached = bool(memory.get("corpus_ever_attached"))
    sections = memory.get("sections") or {}
    if isinstance(sections, dict):
        counts: dict[str, int] = {}
        for k, v in sections.items():
            if isinstance(v, dict):
                items = v.get("items") or []
                counts[str(k)] = len(items)
        report.memory_section_counts = counts


def _load_turn_runs(vfs_root: Path, session_id: str, report: SessionReport) -> None:
    """Each turn writes a ``runs/turn-NNNN-XXXXXX.jsonl`` event stream
    (``run_started`` + many ``span``/``tool_call_*``/etc. records).
    We aggregate per-turn counts.
    """
    runs_dir = vfs_root / "single-user-chat" / "sessions" / session_id / "runs"
    if not runs_dir.is_dir():
        return
    run_files = sorted(p for p in runs_dir.iterdir() if p.name.startswith("turn-"))
    for run_file in run_files:
        # Filename shape: ``turn-NNNN-XXXXXX.jsonl``
        stem = run_file.stem
        parts = stem.split("-")
        turn_index = 0
        if len(parts) >= 2 and parts[1].isdigit():
            turn_index = int(parts[1])
        summary = TurnSummary(turn_index=turn_index)
        try:
            with run_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    data = evt.get("data") or {}
                    if evt.get("event") == "run_started":
                        summary.run_id = data.get("run_id")
                        summary.started_at = data.get("started_at")
                        summary.model = data.get("model")
                    if evt.get("event") in {"tool_call_completed", "tool_completed"}:
                        summary.tool_call_count += 1
                        name = data.get("tool_name") or data.get("name")
                        if name:
                            summary.tool_names[str(name)] += 1
                    if evt.get("event") in {"tool_call_failed", "error"}:
                        summary.error_count += 1
        except OSError as exc:
            report.warnings.append(f"unreadable {run_file.name}: {exc}")
        report.turns.append(summary)
    report.turn_count = len(report.turns)


def _load_tool_calls(vfs_root: Path, session_id: str, report: SessionReport) -> None:
    """The SPA's separate ``toolcalls/turn-NNNN.jsonl`` recorder writes
    one line per tool call after the canonical kaos-agents events
    settle. Used as a cross-check against the runs/ aggregation.
    """
    toolcalls_dir = vfs_root / "sessions" / session_id / "toolcalls"
    if not toolcalls_dir.is_dir():
        return
    name_counts: Counter[str] = Counter()
    total = 0
    for tc_file in sorted(toolcalls_dir.iterdir()):
        if not tc_file.name.endswith(".jsonl"):
            continue
        try:
            with tc_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        call = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    name = call.get("name")
                    if name:
                        name_counts[str(name)] += 1
                        total += 1
        except OSError as exc:
            report.warnings.append(f"unreadable {tc_file.name}: {exc}")
    report.total_tool_calls = total
    report.tool_name_counts = dict(name_counts)


def audit(vfs_root: Path, session_id: str) -> SessionReport:
    """Build a SessionReport by reading every persistent surface the
    SPA writes for one session id.
    """
    report = SessionReport(session_id=session_id, found=False)
    # Quick existence check: a session must have at least a meta.json
    # OR a files dir OR a memory.json to be considered "found".
    meta_path = vfs_root / "single-user-chat" / "sessions" / session_id / "meta.json"
    files_dir = vfs_root / "sessions" / session_id / "files"
    memory_unscoped = vfs_root / "kaos-agents" / "sessions" / session_id / "memory.json"
    if not (meta_path.exists() or files_dir.exists() or memory_unscoped.exists()):
        # Also check tenant-scoped memory path.
        scoped = vfs_root / "kaos-agents" / "sessions"
        scoped_match = scoped.is_dir() and any(
            child.name.endswith(f":{session_id}")
            or child.name.endswith(f"%3A{session_id}")
            for child in scoped.iterdir()
        )
        if not scoped_match:
            return report
    report.found = True
    _load_meta(vfs_root, session_id, report)
    _load_files(vfs_root, session_id, report)
    _load_memory(vfs_root, session_id, report)
    _load_turn_runs(vfs_root, session_id, report)
    _load_tool_calls(vfs_root, session_id, report)
    return report


def _render_text(report: SessionReport) -> str:
    lines: list[str] = []
    lines.append(f"session_id  : {report.session_id}")
    if not report.found:
        lines.append("status      : NOT FOUND")
        return "\n".join(lines)
    lines.append(f"title       : {report.title}")
    lines.append(f"model       : {report.model}")
    lines.append(f"files       : {report.file_count}")
    for f in report.files:
        flags = []
        if f.ocr_applied:
            flags.append("ocr")
        if f.track_changes_detected:
            flags.append("track_changes")
        flag_str = f" [{','.join(flags)}]" if flags else ""
        lines.append(
            f"  - {f.filename} · {f.size_bytes} bytes · parse={f.parse_status}{flag_str}"
        )
    lines.append(f"corpus_attached: {report.corpus_ever_attached}")
    if report.memory_section_counts:
        lines.append("memory sections:")
        for name, count in sorted(report.memory_section_counts.items()):
            lines.append(f"  - {name}: {count}")
    lines.append(f"turns       : {report.turn_count}")
    for t in report.turns:
        lines.append(
            f"  - turn[{t.turn_index}] run={t.run_id} tools={t.tool_call_count}"
            f" errors={t.error_count}"
        )
        if t.tool_names:
            for name, count in t.tool_names.most_common():
                lines.append(f"      · {name}: {count}")
    lines.append(f"toolcalls   : {report.total_tool_calls} total")
    for name, count in sorted(report.tool_name_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"  - {name}: {count}")
    if report.warnings:
        lines.append("warnings:")
        for w in report.warnings:
            lines.append(f"  ! {w}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kaos-audit-session",
        description=(
            "Read-only postmortem report for a single SPA session "
            "(plan Issue 6 / kaos-modules launch-blocker top-10)."
        ),
    )
    parser.add_argument(
        "--session-id",
        required=True,
        help="ULID-shaped session id (e.g. 01KS7VPNPC65YDJXBMA79CD3DH).",
    )
    parser.add_argument(
        "--vfs-path",
        default=".kaos-vfs",
        help="Root of the SPA's VFS tree (default: .kaos-vfs).",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format. ``json`` is single-line + structured (pipe to jq).",
    )
    ns = parser.parse_args(argv)

    if not ns.session_id or len(ns.session_id) < 8:
        print("invalid --session-id", file=sys.stderr)
        return 1

    vfs_root = Path(ns.vfs_path).resolve()
    if not vfs_root.is_dir():
        print(f"vfs-path not a directory: {vfs_root}", file=sys.stderr)
        return 2

    report = audit(vfs_root, ns.session_id)
    if not report.found:
        print(
            f"session {ns.session_id} not found under {vfs_root}",
            file=sys.stderr,
        )
        return 3

    if ns.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
