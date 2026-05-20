#!/usr/bin/env python3
"""Diagnostic CLI for the single-user-chat SPA + kaos-agents persistence layer.

Usage
-----
    python audit_session.py <SESSION_ID> [options]

Options
-------
    --json              JSON output to stdout (machine-readable)
    --verbose           include full tool-result bodies (not previews)
    --vfs PATH          override the VFS root
                        (default: ./examples/single-user-chat/backend/.kaos-vfs/
                         walked up from the script)
    --no-color          force off ANSI colors (also auto-off when not a TTY)
    --turn N            audit only this turn (default: all)
    --quiet             only print the red-flag summary, no per-action detail
    -h, --help          show this help and exit

Exit code
---------
    0 if no red flags were found, 1 if any red flag fired (regression-gate
    friendly).

Why this exists
---------------
The SPA's wire-side tool-call recorder (`toolcalls/turn-NNNN.jsonl`) only
captures the FINAL recovered round of tool calls in some flows. The
kaos-agents `memory.json` action trace, by contrast, is the ground truth.
On the NDA regression matrix run of 2026-05-18, a session that looked
PASS based on `turn-0000.jsonl` had **five prior
`kaos-content-search-document` failures** persisted with
`is_error: false` but with bodies starting `{"error": true, ...}` — the
truncated `result_preview` hid them. This script reads every available
persistence source for a session, cross-references them, and surfaces
red flags the human audit shouldn't have to grep for.

Red-flag catalog
----------------
    A  body-says-error-but-is_error-false
        result_summary contains `"error": true` or `"is_error": true`
        as a JSON literal while tool_execution.is_error is False.
    B  sidecar artifact-lookup failure
        result_summary contains "Failed to load document artifact" or
        "Unknown artifact. Verify the artifact_id".
    C  repeat-failure streak
        Same tool failing N>=3 times consecutively (counts A and explicit
        is_error=True).
    D  inline-cost-vs-meta-cost gap > 3x
        sum(action_trace.cost_usd) vs meta.last_turn_cost_usd > 3x apart.
    E  deliverable-header-then-stop
        Assistant message ends near a markdown heading whose text matches
        a known deliverable keyword AND the rest of the message is <200
        chars (P0-4 #436).
    F  fabricated section number
        Quoted "Section N" / "§ N" in an assistant message where N is
        not present in the cited file's parsed AST sidecar.
        (TODO: prototype heuristic — see code.)
    G  empty/zero-match search
        kaos-content-search-document returning "Found 0 match(es)".
    H  title still equals raw prompt
        meta.title looks like a truncated raw prompt AND
        meta.title_source == "auto".

Data sources scanned
--------------------
    {vfs}/single-user-chat/sessions/{SID}/meta.json
    {vfs}/kaos-agents/sessions/{SID}/memory.json
    {vfs}/sessions/{SID}/toolcalls/turn-NNNN.jsonl
    {vfs}/sessions/{SID}/files/*  (+ .meta.json, + .kaos.json sidecars)
    /tmp/spa-backend.log, /tmp/spa-backend-new.log  (optional, lines
    mentioning SID)

Smoke-test
----------
    cd /home/mjbommar/projects/273v/kaos-ui/examples/single-user-chat/backend
    python ../scripts/audit_session.py 01KRYT3S5H6V3MQYA0DZ825CYX

Stdlib only — no extra deps. Self-contained.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────── constants ──────────────────────────────

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

DELIVERABLE_KEYWORDS = (
    "table",
    "list",
    "summary",
    "csv",
    "memo",
    "comparison",
    "scorecard",
    "review",
)

ARTIFACT_FAILURE_NEEDLES = (
    "Failed to load document artifact",
    "Unknown artifact. Verify the artifact_id",
)

REPEAT_FAILURE_THRESHOLD = 3
COST_GAP_FACTOR = 3.0
DELIVERABLE_TAIL_THRESHOLD_CHARS = 200

# ──────────────────────────── ANSI ──────────────────────────────────


@dataclass
class Style:
    enabled: bool

    def red(self, s: str) -> str:
        return f"\x1b[31m{s}\x1b[0m" if self.enabled else s

    def bold(self, s: str) -> str:
        return f"\x1b[1m{s}\x1b[0m" if self.enabled else s

    def dim(self, s: str) -> str:
        return f"\x1b[2m{s}\x1b[0m" if self.enabled else s

    def green(self, s: str) -> str:
        return f"\x1b[32m{s}\x1b[0m" if self.enabled else s

    def yellow(self, s: str) -> str:
        return f"\x1b[33m{s}\x1b[0m" if self.enabled else s


# ───────────────────── data containers ──────────────────────────────


@dataclass
class FlagHit:
    """One detection of a red flag."""

    code: str  # 'A' .. 'H'
    label: str
    detail: str
    where: str  # short human-readable location ("action #3", "msg #1", etc.)


@dataclass
class ActionRecord:
    """Normalized view of a kaos-agents action item."""

    index: int
    tool_name: str
    is_error: bool
    body_says_error: bool
    artifact_failure: bool
    zero_match: bool
    result_summary: str
    duration_ms: float
    cost_usd: float
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]


@dataclass
class MessageRecord:
    """Normalized view of a memory message."""

    index: int
    role: str  # 'user' / 'assistant' / unknown
    content: str


@dataclass
class FileRecord:
    filename: str
    size_bytes: int
    mime: str | None
    parse_status: str | None
    has_kaos_sidecar: bool


@dataclass
class AuditReport:
    session_id: str
    sources_present: dict[str, bool]
    meta: dict[str, Any] | None
    files: list[FileRecord]
    actions: list[ActionRecord]
    messages: list[MessageRecord]
    toolcalls_count: int
    flags: list[FlagHit] = field(default_factory=list)
    log_warnings: list[str] = field(default_factory=list)
    # cost reconciliation
    action_cost_sum: float = 0.0
    # warnings about malformed/missing sources
    notes: list[str] = field(default_factory=list)


# ─────────────────────────── helpers ────────────────────────────────


def _load_json(path: Path, notes: list[str]) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        notes.append(f"could not read {path}: {exc}")
        return None


def _iter_jsonl(path: Path, notes: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    notes.append(f"{path}:{lineno} malformed JSONL: {exc}")
    except FileNotFoundError:
        return []
    except OSError as exc:
        notes.append(f"could not read {path}: {exc}")
    return out


def _detect_body_error(result_summary: str) -> bool:
    """True if the body text contains a JSON-literal error marker.

    Matches `"error": true` and `"is_error": true` with optional
    whitespace, as serialized by tools that return error dicts.
    """
    if not result_summary:
        return False
    # Allow optional spaces; case-sensitive (JSON literals are lowercase).
    return bool(
        re.search(r'"error"\s*:\s*true', result_summary)
        or re.search(r'"is_error"\s*:\s*true', result_summary)
    )


def _detect_artifact_failure(result_summary: str) -> bool:
    return any(needle in (result_summary or "") for needle in ARTIFACT_FAILURE_NEEDLES)


def _detect_zero_match(tool_name: str, result_summary: str) -> bool:
    if tool_name != "kaos-content-search-document":
        return False
    return "Found 0 match(es)" in (result_summary or "")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        # fromisoformat handles trailing Z in 3.11+; be defensive.
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _human_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "?"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _bytes_human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024.0:
            return f"{f:.1f} {unit}"
        f /= 1024.0
    return f"{f:.1f} TB"


def _looks_like_truncated_prompt(title: str) -> bool:
    """Heuristic: title ends with the ellipsis char and is sentence-ish."""
    if not title:
        return False
    return title.rstrip().endswith(("…", "..."))


# ───────────────────── ingestion functions ──────────────────────────


def _load_meta(vfs: Path, sid: str, notes: list[str]) -> dict[str, Any] | None:
    p = vfs / "single-user-chat" / "sessions" / sid / "meta.json"
    return _load_json(p, notes)


def _load_memory(
    vfs: Path, sid: str, notes: list[str]
) -> tuple[list[ActionRecord], list[MessageRecord], bool]:
    p = vfs / "kaos-agents" / "sessions" / sid / "memory.json"
    data = _load_json(p, notes)
    if data is None:
        return [], [], False

    sections = data.get("sections", {}) if isinstance(data, dict) else {}
    actions_items = (
        sections.get("actions", {}).get("items", [])
        if isinstance(sections.get("actions"), dict)
        else []
    )
    messages_items = (
        sections.get("messages", {}).get("items", [])
        if isinstance(sections.get("messages"), dict)
        else []
    )

    actions: list[ActionRecord] = []
    for i, item in enumerate(actions_items):
        if not isinstance(item, dict):
            notes.append(f"action #{i}: not a dict, skipping")
            continue
        te = (item.get("metadata") or {}).get("tool_execution") or {}
        tool_name = te.get("tool_name") or "?"
        is_error = bool(te.get("is_error"))
        result_summary = te.get("result_summary") or ""
        actions.append(
            ActionRecord(
                index=i,
                tool_name=tool_name,
                is_error=is_error,
                body_says_error=_detect_body_error(result_summary),
                artifact_failure=_detect_artifact_failure(result_summary),
                zero_match=_detect_zero_match(tool_name, result_summary),
                result_summary=result_summary,
                duration_ms=float(te.get("duration_ms") or 0.0),
                cost_usd=float(te.get("cost_usd") or 0.0),
                input_tokens=int(te.get("input_tokens") or 0),
                output_tokens=int(te.get("output_tokens") or 0),
                raw=item,
            )
        )

    messages: list[MessageRecord] = []
    for i, item in enumerate(messages_items):
        if not isinstance(item, dict):
            notes.append(f"message #{i}: not a dict, skipping")
            continue
        content = item.get("content") or ""
        role = "unknown"
        # memory stores messages as "user: ..." / "assistant: ..."
        if content.startswith("user:"):
            role = "user"
            content = content[len("user:") :].lstrip()
        elif content.startswith("assistant:"):
            role = "assistant"
            content = content[len("assistant:") :].lstrip()
        messages.append(MessageRecord(index=i, role=role, content=content))

    return actions, messages, True


def _load_files(vfs: Path, sid: str, notes: list[str]) -> list[FileRecord]:
    files_dir = vfs / "sessions" / sid / "files"
    if not files_dir.is_dir():
        return []
    out: list[FileRecord] = []
    try:
        children = sorted(files_dir.iterdir())
    except OSError as exc:
        notes.append(f"could not list {files_dir}: {exc}")
        return []
    for child in children:
        name = child.name
        # Skip sidecars when enumerating primary files.
        if name.endswith(".meta.json") or name.endswith(".kaos.json"):
            continue
        try:
            size = child.stat().st_size
        except OSError as exc:
            notes.append(f"could not stat {child}: {exc}")
            size = 0
        meta_path = child.with_name(name + ".meta.json")
        meta = _load_json(meta_path, notes) if meta_path.exists() else None
        mime = None
        parse_status = None
        if isinstance(meta, dict):
            mime = meta.get("content_type")
            parse = meta.get("parse") or {}
            if isinstance(parse, dict):
                parse_status = parse.get("status")
        kaos_path = child.with_name(name + ".kaos.json")
        out.append(
            FileRecord(
                filename=name,
                size_bytes=size,
                mime=mime,
                parse_status=parse_status,
                has_kaos_sidecar=kaos_path.exists(),
            )
        )
    return out


def _count_toolcalls(vfs: Path, sid: str, notes: list[str]) -> tuple[int, list[Path]]:
    toolcalls_dir = vfs / "sessions" / sid / "toolcalls"
    if not toolcalls_dir.is_dir():
        return 0, []
    paths = sorted(toolcalls_dir.glob("turn-*.jsonl"))
    total = 0
    for p in paths:
        total += len(_iter_jsonl(p, notes))
    return total, paths


def _scan_logs(sid: str) -> list[str]:
    candidates = [Path("/tmp/spa-backend.log"), Path("/tmp/spa-backend-new.log")]
    hits: list[str] = []
    for p in candidates:
        if not p.is_file():
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if sid not in line:
                        continue
                    if "WARNING" in line or "ERROR" in line:
                        # Drop the noisy unauthenticated-dev banner — it's
                        # informational, not an indicator of session health.
                        if "unauthenticated localhost-dev request" in line:
                            continue
                        hits.append(f"{p.name}: {line.rstrip()}")
        except OSError:
            continue
    return hits


# ─────────────────────── red-flag detection ─────────────────────────


def _flag_actions(actions: list[ActionRecord], flags: list[FlagHit]) -> None:
    """Per-action red flags A, B, G."""
    for a in actions:
        if a.body_says_error and not a.is_error:
            flags.append(
                FlagHit(
                    code="A",
                    label="body-says-error-but-is_error-false",
                    detail=(
                        f"{a.tool_name}: result_summary has JSON error literal "
                        "but tool_execution.is_error=False"
                    ),
                    where=f"action #{a.index}",
                )
            )
        if a.artifact_failure:
            flags.append(
                FlagHit(
                    code="B",
                    label="sidecar artifact-lookup failure",
                    detail=(
                        f"{a.tool_name}: artifact-store lookup failed "
                        f"({_first_line(a.result_summary, 140)})"
                    ),
                    where=f"action #{a.index}",
                )
            )
        if a.zero_match:
            flags.append(
                FlagHit(
                    code="G",
                    label="empty/zero-match search",
                    detail=f"{a.tool_name} returned 'Found 0 match(es)'",
                    where=f"action #{a.index}",
                )
            )


def _flag_streaks(actions: list[ActionRecord], flags: list[FlagHit]) -> None:
    """Red flag C — same tool failing N>=3 consecutively."""
    if not actions:
        return
    current_tool: str | None = None
    streak = 0
    streak_start = 0
    for a in actions:
        failed = a.is_error or a.body_says_error or a.artifact_failure
        if failed and a.tool_name == current_tool:
            streak += 1
        elif failed:
            current_tool = a.tool_name
            streak = 1
            streak_start = a.index
        else:
            if streak >= REPEAT_FAILURE_THRESHOLD and current_tool is not None:
                flags.append(
                    FlagHit(
                        code="C",
                        label="repeat-failure streak",
                        detail=(
                            f"{current_tool} failed x{streak} consecutively"
                        ),
                        where=f"actions #{streak_start}..#{streak_start + streak - 1}",
                    )
                )
            current_tool = None
            streak = 0
    if streak >= REPEAT_FAILURE_THRESHOLD and current_tool is not None:
        flags.append(
            FlagHit(
                code="C",
                label="repeat-failure streak",
                detail=f"{current_tool} failed x{streak} consecutively",
                where=f"actions #{streak_start}..#{streak_start + streak - 1}",
            )
        )


def _flag_cost_gap(
    report: AuditReport, flags: list[FlagHit]
) -> None:
    """Red flag D — meta cost vs action-trace cost sum gap > 3x."""
    if not report.meta:
        return
    meta_cost = report.meta.get("last_turn_cost_usd") or 0.0
    try:
        meta_cost = float(meta_cost)
    except (TypeError, ValueError):
        return
    trace_cost = report.action_cost_sum
    # Treat near-zero as zero to avoid div-by-zero noise.
    if meta_cost < 1e-6 and trace_cost < 1e-6:
        return
    # If one side is essentially zero, report that explicitly instead of
    # spitting out a 500-million-x ratio.
    if min(meta_cost, trace_cost) < 1e-6:
        flags.append(
            FlagHit(
                code="D",
                label="inline-cost-vs-meta-cost gap > 3x",
                detail=(
                    f"meta.last_turn_cost_usd=${meta_cost:.4f} vs "
                    f"sum(action.cost_usd)=${trace_cost:.4f}  "
                    "(one side is ~0 — action trace likely missing cost data)"
                ),
                where="meta vs action trace",
            )
        )
        return
    larger = max(meta_cost, trace_cost)
    smaller = min(meta_cost, trace_cost)
    ratio = larger / smaller
    if ratio > COST_GAP_FACTOR:
        flags.append(
            FlagHit(
                code="D",
                label="inline-cost-vs-meta-cost gap > 3x",
                detail=(
                    f"meta.last_turn_cost_usd=${meta_cost:.4f} vs "
                    f"sum(action.cost_usd)=${trace_cost:.4f}  ({ratio:.1f}x gap)"
                ),
                where="meta vs action trace",
            )
        )


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _flag_deliverable_header_stop(
    messages: list[MessageRecord], flags: list[FlagHit]
) -> None:
    """Red flag E — assistant ends near a deliverable header with thin body."""
    for m in messages:
        if m.role != "assistant" or not m.content:
            continue
        text = m.content.rstrip()
        # Find the LAST heading occurrence.
        last = None
        for match in _HEADING_RE.finditer(text):
            last = match
        if not last:
            continue
        heading_text = last.group(2).lower()
        if not any(kw in heading_text for kw in DELIVERABLE_KEYWORDS):
            continue
        # Characters AFTER the heading line (the body that should follow).
        after = text[last.end() :].strip()
        if len(after) >= DELIVERABLE_TAIL_THRESHOLD_CHARS:
            continue
        flags.append(
            FlagHit(
                code="E",
                label="deliverable-header-then-stop",
                detail=(
                    f"message ends with heading '{last.group(2)}' "
                    f"and only {len(after)} chars follow (<200)"
                ),
                where=f"message #{m.index}",
            )
        )


# TODO(red-flag-F): fabricated section number detection.
# A correct implementation needs to (a) parse each cited file's
# .kaos.json AST to enumerate the *actual* section numbers in the
# document body and headers, accounting for kelvin-office-style
# numbering.xml lists (see MEMORY.md: kelvin-office list numbering),
# then (b) compare against "Section N" / "§ N" mentions in the
# assistant message. The AST walk is non-trivial (kelvin-office
# stripping the numeral is exactly the bug surface that makes naive
# "search for 'Section 7'" unreliable). Left as a TODO so we don't
# ship a heuristic that produces false fabrication accusations.
def _flag_fabricated_section(
    _messages: list[MessageRecord], _files: list[FileRecord], _vfs: Path, _sid: str
) -> list[FlagHit]:
    return []


def _flag_title(meta: dict[str, Any] | None, flags: list[FlagHit]) -> None:
    """Red flag H — auto title still equals the truncated raw prompt."""
    if not meta:
        return
    if meta.get("title_source") != "auto":
        return
    title = meta.get("title") or ""
    if _looks_like_truncated_prompt(title):
        flags.append(
            FlagHit(
                code="H",
                label="auto title still looks like raw prompt",
                detail=(
                    f"title={title!r}, title_source=auto — "
                    "auto-titler may have failed or not yet fired"
                ),
                where="meta.title",
            )
        )


def _first_line(s: str, limit: int) -> str:
    """First non-empty line of s, truncated to limit chars."""
    if not s:
        return ""
    for raw in s.splitlines():
        raw = raw.strip()
        if raw:
            return (raw[: limit - 1] + "…") if len(raw) > limit else raw
    return ""


# ──────────────────────────── audit ────────────────────────────────


def run_audit(vfs: Path, sid: str, turn_filter: int | None) -> AuditReport:
    notes: list[str] = []

    meta = _load_meta(vfs, sid, notes)
    actions, messages, memory_present = _load_memory(vfs, sid, notes)
    files = _load_files(vfs, sid, notes)
    toolcalls_count, _toolcall_paths = _count_toolcalls(vfs, sid, notes)
    log_warnings = _scan_logs(sid)

    # `--turn N` is best-effort: memory.json doesn't carry per-action turn
    # IDs in the current schema; we use it only to limit toolcalls + the
    # message slice. If the filter doesn't apply cleanly we keep all data.
    if turn_filter is not None and 0 <= turn_filter < len(messages) // 2:
        # one turn ≈ (user msg, assistant msg); slice messages window.
        lo = turn_filter * 2
        hi = lo + 2
        messages = messages[lo:hi]
        # No reliable per-action turn id; leave actions untouched and note it.
        notes.append(
            f"--turn {turn_filter}: action trace is not split by turn in "
            "memory.json; showing all actions."
        )

    report = AuditReport(
        session_id=sid,
        sources_present={
            "meta.json": meta is not None,
            "memory.json": memory_present,
            "files": bool(files),
            "toolcalls": toolcalls_count > 0,
            "logs": bool(log_warnings),
        },
        meta=meta,
        files=files,
        actions=actions,
        messages=messages,
        toolcalls_count=toolcalls_count,
        log_warnings=log_warnings,
        notes=notes,
    )
    report.action_cost_sum = sum(a.cost_usd for a in actions)

    _flag_actions(actions, report.flags)
    _flag_streaks(actions, report.flags)
    _flag_cost_gap(report, report.flags)
    _flag_deliverable_header_stop(messages, report.flags)
    report.flags.extend(_flag_fabricated_section(messages, files, vfs, sid))
    _flag_title(meta, report.flags)

    return report


# ──────────────────────── output renderers ─────────────────────────


def _render_human(
    report: AuditReport,
    style: Style,
    verbose: bool,
    quiet: bool,
) -> str:
    out: list[str] = []
    bar = "═" * 63
    out.append(bar)
    out.append(f"Session {style.bold(report.session_id)}")
    out.append(bar)

    if not any(report.sources_present.values()):
        out.append(
            style.red(
                "No persistence sources found for this session id. "
                "Wrong VFS root, or never created?"
            )
        )
        out.append(f"VFS root scanned: {style.dim(str(_resolve_for_msg))}")
        return "\n".join(out) + "\n"

    # missing-source notes
    missing = [k for k, v in report.sources_present.items() if not v]
    if missing:
        out.append(style.dim(f"(missing sources: {', '.join(missing)})"))

    # ── header block ────────────────────────────────────────────────
    meta = report.meta or {}
    title = meta.get("title") or "<no title>"
    title_src = meta.get("title_source") or "?"
    model = meta.get("model") or "?"
    build_sha = meta.get("build_sha") or "?"
    created = meta.get("created_at") or "?"
    last_msg = meta.get("last_message_at") or "?"
    msg_count = meta.get("message_count")
    total_cost = meta.get("total_cost_usd") or 0.0
    total_tokens = meta.get("total_tokens") or 0

    delta = ""
    c_dt = _parse_iso(meta.get("created_at"))
    l_dt = _parse_iso(meta.get("last_message_at"))
    if c_dt and l_dt:
        delta = f" ({_human_duration((l_dt - c_dt).total_seconds())})"

    out.append(f"Title:       {title}  ({title_src})")
    out.append(f"Model:       {model}")
    out.append(f"Build SHA:   {build_sha}")
    out.append(f"Created:     {created}  ->  Last msg: {last_msg}{delta}")
    if msg_count is not None:
        out.append(f"Messages:    {msg_count}")
    try:
        out.append(
            f"Total cost:  ${float(total_cost):.4f}   ·   "
            f"Total tokens: {int(total_tokens):,}"
        )
    except (TypeError, ValueError):
        out.append(f"Total cost:  {total_cost}   ·   Total tokens: {total_tokens}")

    # ── files ──────────────────────────────────────────────────────
    if report.files:
        out.append("")
        out.append(f"Files ({len(report.files)}):")
        for f in report.files:
            parsed = "parsed ok" if f.parse_status == "ready" else (
                f"parse={f.parse_status or '?'}"
            )
            sidecar = "sidecar ok" if f.has_kaos_sidecar else style.yellow(
                "no .kaos.json"
            )
            out.append(
                f"  {f.filename:<32s}  {_bytes_human(f.size_bytes):>9s}   "
                f"{parsed} · {sidecar}"
            )

    # ── toolcalls vs action gap ────────────────────────────────────
    if report.actions or report.toolcalls_count:
        gap_note = ""
        if report.toolcalls_count < len(report.actions):
            gap_note = style.yellow(
                f"  (recorder undercount: jsonl={report.toolcalls_count} "
                f"vs memory={len(report.actions)})"
            )
        out.append("")
        out.append(
            f"Action trace:  memory.json={len(report.actions)}  ·  "
            f"toolcalls.jsonl={report.toolcalls_count}{gap_note}"
        )

    # ── per-turn / per-action ──────────────────────────────────────
    flags_by_action: dict[int, list[FlagHit]] = {}
    for f in report.flags:
        # extract action index where present
        m = re.search(r"action #(\d+)", f.where)
        if m:
            flags_by_action.setdefault(int(m.group(1)), []).append(f)

    if not quiet:
        out.append("")
        out.append(f"Turn detail  (cost sum=${report.action_cost_sum:.4f})")
        out.append("-" * 63)
        for a in report.actions:
            line = (
                f"  [{a.index:2d}] {a.tool_name:<38s}  "
                f"is_err={'T' if a.is_error else 'F'}  "
                f"{a.output_tokens:>4d}tok  "
                f"{a.duration_ms:>7.1f}ms  "
                f"${a.cost_usd:.4f}"
            )
            tags: list[str] = []
            for fl in flags_by_action.get(a.index, []):
                tag = f"Red Flag {fl.code}"
                tags.append(style.red(tag))
            if a.zero_match and not any(
                fl.code == "G" for fl in flags_by_action.get(a.index, [])
            ):
                tags.append(style.yellow("zero-match"))
            if tags:
                line += "    " + " · ".join(tags)
            out.append(line)
            if verbose and a.result_summary:
                for body_line in a.result_summary.splitlines():
                    out.append(f"        {body_line}")
            elif flags_by_action.get(a.index):
                preview = _first_line(a.result_summary, 200)
                if preview:
                    out.append(style.dim(f"        body: {preview}"))

    # ── messages preview ───────────────────────────────────────────
    if report.messages and not quiet:
        out.append("")
        out.append("Messages")
        out.append("-" * 63)
        for m in report.messages:
            head = m.content[:160].replace("\n", " ")
            tail = m.content[-200:].replace("\n", " ") if len(m.content) > 160 else ""
            out.append(f"  [{m.index}] {m.role}: {head}")
            if tail and tail != head:
                out.append(style.dim(f"      ... tail: {tail}"))

    # ── log warnings ───────────────────────────────────────────────
    if report.log_warnings:
        out.append("")
        out.append(f"Log lines mentioning {report.session_id}:")
        for line in report.log_warnings[:20]:
            out.append(f"  {style.yellow(line)}")
        if len(report.log_warnings) > 20:
            out.append(
                style.dim(f"  ... and {len(report.log_warnings) - 20} more")
            )

    # ── flag summary ───────────────────────────────────────────────
    out.append("")
    out.append("Summary")
    out.append("-" * 63)
    if not report.flags:
        out.append("  " + style.green("No red flags. PASS."))
    else:
        # group by code
        counts: dict[str, int] = {}
        for f in report.flags:
            counts[f.code] = counts.get(f.code, 0) + 1
        parts = ", ".join(f"{c}x{n}" for c, n in sorted(counts.items()))
        out.append("  Red flags: " + style.red(parts))
        for f in report.flags:
            line = f"    [{f.code}] {f.label} ({f.where}): {f.detail}"
            out.append(style.red(line))

    if report.notes:
        out.append("")
        out.append("Notes:")
        for n in report.notes:
            out.append(style.dim(f"  - {n}"))

    out.append(bar)
    return "\n".join(out) + "\n"


def _render_json(report: AuditReport) -> str:
    payload = {
        "session_id": report.session_id,
        "sources_present": report.sources_present,
        "meta": report.meta,
        "files": [
            {
                "filename": f.filename,
                "size_bytes": f.size_bytes,
                "mime": f.mime,
                "parse_status": f.parse_status,
                "has_kaos_sidecar": f.has_kaos_sidecar,
            }
            for f in report.files
        ],
        "actions": [
            {
                "index": a.index,
                "tool_name": a.tool_name,
                "is_error": a.is_error,
                "body_says_error": a.body_says_error,
                "artifact_failure": a.artifact_failure,
                "zero_match": a.zero_match,
                "result_summary": a.result_summary,
                "duration_ms": a.duration_ms,
                "cost_usd": a.cost_usd,
                "input_tokens": a.input_tokens,
                "output_tokens": a.output_tokens,
            }
            for a in report.actions
        ],
        "messages": [
            {"index": m.index, "role": m.role, "content": m.content}
            for m in report.messages
        ],
        "toolcalls_count": report.toolcalls_count,
        "action_cost_sum": report.action_cost_sum,
        "flags": [
            {"code": f.code, "label": f.label, "detail": f.detail, "where": f.where}
            for f in report.flags
        ],
        "log_warnings": report.log_warnings,
        "notes": report.notes,
    }
    return json.dumps(payload, indent=2, default=str) + "\n"


# ──────────────────────── VFS resolution ───────────────────────────


# kept module-level so the "no sources" branch in _render_human can show
# the resolved path even though it's computed in main().
_resolve_for_msg = ""


def _default_vfs_root() -> Path:
    """Walk up from this script to find the SPA backend VFS.

    The script lives at:
        examples/single-user-chat/scripts/audit_session.py
    The VFS lives at:
        examples/single-user-chat/backend/.kaos-vfs/
    """
    here = Path(__file__).resolve().parent
    # parents[0]=scripts, parents[1]=single-user-chat
    candidate = here.parent / "backend" / ".kaos-vfs"
    if candidate.is_dir():
        return candidate
    # Also accept CWD-relative path (CLI ran from elsewhere).
    cwd_candidate = Path.cwd() / ".kaos-vfs"
    if cwd_candidate.is_dir():
        return cwd_candidate
    cwd_alt = Path.cwd() / "examples" / "single-user-chat" / "backend" / ".kaos-vfs"
    if cwd_alt.is_dir():
        return cwd_alt
    return candidate  # best-effort, will surface as "missing sources" later


# ──────────────────────────── main ─────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_session.py",
        description=(
            "Audit a single-user-chat SPA session: surface tool-call "
            "failures hidden under is_error=False, deliverable stops, "
            "cost gaps, and other red flags."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("session_id", help="ULID of the session to audit")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--verbose", action="store_true", help="include full tool-result bodies"
    )
    parser.add_argument(
        "--vfs",
        type=Path,
        default=None,
        help="override VFS root (default: ./examples/single-user-chat/backend/.kaos-vfs/)",
    )
    parser.add_argument("--no-color", action="store_true", help="force off ANSI colors")
    parser.add_argument(
        "--turn", type=int, default=None, help="audit only this turn (default: all)"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="only print the red-flag summary"
    )
    args = parser.parse_args(argv)

    sid = args.session_id.strip()
    if not ULID_RE.match(sid):
        print(
            f"error: '{sid}' does not look like a ULID "
            "(26 chars, Crockford base32). Check the session id.",
            file=sys.stderr,
        )
        return 2

    vfs = args.vfs.expanduser().resolve() if args.vfs else _default_vfs_root()
    global _resolve_for_msg
    _resolve_for_msg = str(vfs)
    if not vfs.is_dir():
        print(
            f"error: VFS root not found: {vfs}\n"
            "       Pass --vfs PATH or run from the SPA backend cwd.",
            file=sys.stderr,
        )
        return 2

    report = run_audit(vfs, sid, args.turn)

    if args.json:
        sys.stdout.write(_render_json(report))
    else:
        color = (not args.no_color) and sys.stdout.isatty()
        style = Style(enabled=color)
        sys.stdout.write(_render_human(report, style, args.verbose, args.quiet))

    return 1 if report.flags else 0


if __name__ == "__main__":
    sys.exit(main())
