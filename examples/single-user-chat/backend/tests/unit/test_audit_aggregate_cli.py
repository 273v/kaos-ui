"""Unit tests for kaos-audit-aggregate (plan Issue 5).

The aggregator walks the on-disk VFS layout the SPA writes and
produces one JSONL row per completed turn that started on a given
date. These tests build synthetic session trees, run the aggregator,
and assert the output shape + filter behaviour.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.cli.audit_aggregate import aggregate, main


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, tzinfo=UTC).timestamp()


def _build_session(
    vfs: Path,
    *,
    tenant: str | None,
    sid: str,
    started_at: float,
    model: str = "openai:gpt-5.4-mini",
    tokens_in: int = 1500,
    tokens_out: int = 800,
    cost_usd: float = 0.0042,
    tools: tuple[str, ...] = ("kaos-office-parse-docx",),
    intent: str = "complete",
    meta_extra: dict | None = None,
    turn_index: int = 0,
) -> Path:
    """Materialize one session with one turn."""
    scoped = f"{tenant}%3A{sid}" if tenant else sid
    session_dir = vfs / "single-user-chat" / "sessions" / scoped
    runs_dir = session_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": sid,
        "title": "Test",
        "model": model,
        "matter_id": None,
        "hipaa_required": False,
        "privileged": False,
    }
    if meta_extra:
        meta.update(meta_extra)
    (session_dir / "meta.json").write_text(json.dumps(meta))
    run_path = runs_dir / f"turn-{turn_index:04d}-runid{turn_index:02d}.jsonl"
    events = [
        {
            "event": "run_started",
            "data": {
                "run_id": f"run-{turn_index}",
                "started_at": started_at,
                "model": model,
                "build_sha": "deadbeef1234",
            },
        },
        {
            "event": "usage_observed",
            "data": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
            },
        },
    ]
    for tn in tools:
        events.append({"event": "tool_call_completed", "data": {"tool_name": tn}})
    events.append({"event": "turn_summary", "data": {"intent": intent}})
    events.append({"event": "run_completed", "data": {"completed_at": started_at + 30}})
    run_path.write_text("\n".join(json.dumps(e) for e in events))
    return run_path


@pytest.mark.unit
def test_aggregate_includes_only_target_date(tmp_path: Path) -> None:
    """Two sessions: one on 2026-05-22, one on 2026-05-21. Only the
    matching date should appear in the output."""
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01ONFENCE",
        started_at=_ts(2026, 5, 22, 14),
    )
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01OFFFENCE",
        started_at=_ts(2026, 5, 21, 14),
    )
    report = aggregate(tmp_path / ".kaos-vfs", date="2026-05-22")
    assert report.session_count == 2  # both walked
    assert report.turn_count == 1
    assert report.lines[0].session_id == "01ONFENCE"


@pytest.mark.unit
def test_aggregate_tenant_filter_excludes_other_tenants(tmp_path: Path) -> None:
    """Three sessions across two tenants on the same date. Filtering
    by tenant_id must return only that tenant's session(s)."""
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01A",
        started_at=_ts(2026, 5, 22, 9),
    )
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01B",
        started_at=_ts(2026, 5, 22, 10),
    )
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="bbbbbbbbbbbb",
        sid="01C",
        started_at=_ts(2026, 5, 22, 11),
    )
    rep_all = aggregate(tmp_path / ".kaos-vfs", date="2026-05-22")
    assert rep_all.turn_count == 3
    rep_one = aggregate(tmp_path / ".kaos-vfs", date="2026-05-22", tenant_id="11f8f4450cce")
    assert rep_one.turn_count == 2
    assert {r.session_id for r in rep_one.lines} == {"01A", "01B"}


@pytest.mark.unit
def test_aggregate_captures_tokens_cost_and_tools(tmp_path: Path) -> None:
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01XYZ",
        started_at=_ts(2026, 5, 22, 8),
        tokens_in=2500,
        tokens_out=900,
        cost_usd=0.0072,
        tools=("kaos-office-parse-docx", "kaos-content-search-document"),
        intent="complete",
    )
    report = aggregate(tmp_path / ".kaos-vfs", date="2026-05-22")
    line = report.lines[0]
    assert line.tokens_in == 2500
    assert line.tokens_out == 900
    assert line.cost_usd == pytest.approx(0.0072, abs=1e-9)
    assert line.tool_names_invoked == (
        "kaos-office-parse-docx",
        "kaos-content-search-document",
    )
    assert line.intent == "complete"
    assert line.build_sha == "deadbeef1234"


@pytest.mark.unit
def test_aggregate_surfaces_matter_and_policy_from_meta(tmp_path: Path) -> None:
    """Issue 2 + Issue 4: matter_id, hipaa_required, privileged must
    propagate from meta.json into each audit line."""
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01PRIV",
        started_at=_ts(2026, 5, 22, 12),
        meta_extra={
            "matter_id": "ABC-2026-0042",
            "hipaa_required": True,
            "privileged": True,
        },
    )
    report = aggregate(tmp_path / ".kaos-vfs", date="2026-05-22")
    line = report.lines[0]
    assert line.matter_id == "ABC-2026-0042"
    assert line.hipaa_required is True
    assert line.privileged is True


@pytest.mark.unit
def test_aggregate_jsonl_output_is_valid_one_line_per_turn(tmp_path: Path) -> None:
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01A",
        started_at=_ts(2026, 5, 22, 1),
        turn_index=0,
    )
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01A",
        started_at=_ts(2026, 5, 22, 2),
        turn_index=1,
    )
    report = aggregate(tmp_path / ".kaos-vfs", date="2026-05-22")
    out = report.to_jsonl()
    lines = [json.loads(line) for line in out.strip().splitlines()]
    assert len(lines) == 2
    indices = sorted(line["turn_index"] for line in lines)
    assert indices == [0, 1]
    # Every JSONL field round-trips as JSON-compatible.
    for line in lines:
        assert isinstance(line["tool_names_invoked"], list)
        assert isinstance(line["tokens_in"], int)
        assert isinstance(line["cost_usd"], float)


@pytest.mark.unit
def test_main_bad_date_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".kaos-vfs" / "single-user-chat" / "sessions").mkdir(parents=True)
    code = main(["--vfs-path", str(tmp_path / ".kaos-vfs"), "--date", "20260522"])
    assert code == 2
    err = capsys.readouterr().err
    assert "valid YYYY-MM-DD" in err


@pytest.mark.unit
def test_main_no_sessions_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".kaos-vfs" / "single-user-chat" / "sessions").mkdir(parents=True)
    code = main(["--vfs-path", str(tmp_path / ".kaos-vfs"), "--date", "2026-05-22"])
    assert code == 3
    err = capsys.readouterr().err
    assert "no sessions found" in err


@pytest.mark.unit
def test_main_summary_format(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01A",
        started_at=_ts(2026, 5, 22, 1),
    )
    code = main(
        [
            "--vfs-path",
            str(tmp_path / ".kaos-vfs"),
            "--date",
            "2026-05-22",
            "--format",
            "summary",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "sessions=1" in out
    assert "turns=1" in out


@pytest.mark.unit
def test_main_jsonl_format_emits_one_line_per_turn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _build_session(
        tmp_path / ".kaos-vfs",
        tenant="11f8f4450cce",
        sid="01A",
        started_at=_ts(2026, 5, 22, 1),
    )
    code = main(["--vfs-path", str(tmp_path / ".kaos-vfs"), "--date", "2026-05-22"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    rows = [json.loads(line) for line in out.splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["session_id"] == "01A"
    assert rows[0]["tenant_id"] == "11f8f4450cce"
