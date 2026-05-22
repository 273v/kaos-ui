"""Unit tests for the ``kaos-audit-session`` CLI (plan Issue 6).

The CLI is read-only — it walks the session VFS layout the SPA
writes and emits a JSON or text report. These tests build a minimal
fake VFS tree on a tmp_path and assert the CLI surfaces the right
counts, exits with the right codes, and tolerates missing sidecars.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.audit_session import audit, main


def _build_fake_session(vfs_root: Path, sid: str, *, with_track_changes: bool) -> None:
    """Materialize the on-disk shape the SPA writes for one session."""
    # 1. meta.json (single-user-chat namespace)
    meta_dir = vfs_root / "single-user-chat" / "sessions" / sid
    meta_dir.mkdir(parents=True)
    (meta_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": sid,
                "title": "Test session",
                "model": "openai:gpt-5.4-mini",
            }
        )
    )
    # 2. files/ + per-file .meta.json sidecar
    files_dir = vfs_root / "sessions" / sid / "files"
    files_dir.mkdir(parents=True)
    (files_dir / "contract.docx").write_bytes(b"binary docx body")
    (files_dir / "contract.docx.meta.json").write_text(
        json.dumps(
            {
                "filename": "contract.docx",
                "size_bytes": 4096,
                "parse": {"status": "ready"},
                "ocr_applied": False,
                "track_changes_detected": with_track_changes,
            }
        )
    )
    # 3. memory.json with documents + actions sections
    memory_dir = vfs_root / "kaos-agents" / "sessions" / sid
    memory_dir.mkdir(parents=True)
    (memory_dir / "memory.json").write_text(
        json.dumps(
            {
                "session_id": sid,
                "turn_count": 1,
                "corpus_ever_attached": True,
                "sections": {
                    "documents": {"items": [{"content": "filename: contract.docx"}]},
                    "actions": {"items": [{"content": "a1"}, {"content": "a2"}]},
                },
            }
        )
    )
    # 4. runs/turn-0000-XXXXXX.jsonl with one tool_call_completed event
    runs_dir = meta_dir / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "turn-0000-abc123.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "run_started",
                        "data": {
                            "run_id": "run-abc",
                            "started_at": 1779454179.0,
                            "model": "openai:gpt-5.4-mini",
                            "build_sha": "deadbeef1234",
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "tool_call_completed",
                        "data": {"tool_name": "kaos-office-parse-docx"},
                    }
                ),
                json.dumps(
                    {
                        "event": "tool_call_completed",
                        "data": {"tool_name": "kaos-content-stats"},
                    }
                ),
                # Plan Issue 8 — per-turn token + cost aggregation.
                json.dumps(
                    {
                        "event": "usage_observed",
                        "data": {
                            "tokens_in": 1500,
                            "tokens_out": 800,
                            "cost_usd": 0.0042,
                        },
                    }
                ),
                json.dumps(
                    {
                        "event": "usage_observed",
                        "data": {
                            "tokens_in": 700,
                            "tokens_out": 300,
                            "cost_usd": 0.0018,
                        },
                    }
                ),
            ]
        )
    )
    # 5. toolcalls/turn-0000.jsonl (SPA recorder)
    tc_dir = vfs_root / "sessions" / sid / "toolcalls"
    tc_dir.mkdir(parents=True)
    (tc_dir / "turn-0000.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"name": "kaos-office-parse-docx", "status": "done"}),
                json.dumps({"name": "kaos-content-stats", "status": "done"}),
            ]
        )
    )


@pytest.mark.unit
def test_per_turn_token_usage_aggregated(tmp_path: Path) -> None:
    """Plan Issue 8 — long-session degradation tracking. Per-turn
    usage_observed events sum into tokens_in / tokens_out / cost_usd
    on the TurnSummary, which audit reports use to plot the
    degradation curve as a session approaches its context budget.
    """
    sid = "01TESTTOKENSXXXXXXXXXX"
    _build_fake_session(tmp_path, sid, with_track_changes=False)
    report = audit(tmp_path, sid)
    t = report.turns[0]
    # Two usage_observed records: (1500+800) + (700+300) tokens,
    # (0.0042 + 0.0018) USD.
    assert t.tokens_in == 2200
    assert t.tokens_out == 1100
    assert t.cost_usd == pytest.approx(0.0060, abs=1e-9)
    payload = report.to_dict()
    assert payload["turns"][0]["tokens_in"] == 2200
    assert payload["turns"][0]["tokens_out"] == 1100
    assert payload["turns"][0]["cost_usd"] == 0.006


@pytest.mark.unit
def test_per_turn_build_sha_round_trips(tmp_path: Path) -> None:
    """Plan Issue 3 — per-turn version pinning. The run_started event
    carries build_sha, and the audit report exposes it on each turn
    (text + JSON). Sessions created before this commit will have
    build_sha=None and that's intentional — the field is opt-in
    forward-compatible.
    """
    sid = "01TESTBUILDSHAXXXXXXXX"
    _build_fake_session(tmp_path, sid, with_track_changes=False)
    report = audit(tmp_path, sid)
    assert report.turns
    assert report.turns[0].build_sha == "deadbeef1234"
    # JSON round-trip surfaces the field.
    payload = report.to_dict()
    assert payload["turns"][0]["build_sha"] == "deadbeef1234"


@pytest.mark.unit
def test_audit_picks_up_every_persistent_surface(tmp_path: Path) -> None:
    sid = "01TESTSESSIONXXXXXXXXXX"
    _build_fake_session(tmp_path, sid, with_track_changes=True)
    report = audit(tmp_path, sid)

    assert report.found is True
    assert report.title == "Test session"
    assert report.model == "openai:gpt-5.4-mini"
    assert report.file_count == 1
    assert report.files[0].filename == "contract.docx"
    assert report.files[0].track_changes_detected is True
    assert report.files[0].parse_status == "ready"
    assert report.corpus_ever_attached is True
    assert report.memory_section_counts == {"documents": 1, "actions": 2}
    assert report.turn_count == 1
    assert report.turns[0].tool_call_count == 2
    assert dict(report.turns[0].tool_names) == {
        "kaos-office-parse-docx": 1,
        "kaos-content-stats": 1,
    }
    assert report.total_tool_calls == 2
    assert report.tool_name_counts == {
        "kaos-office-parse-docx": 1,
        "kaos-content-stats": 1,
    }
    assert report.warnings == []


@pytest.mark.unit
def test_audit_missing_session_returns_not_found(tmp_path: Path) -> None:
    """No meta + no files + no memory → ``found=False``, no crash."""
    # Make the VFS root exist but with no session matching the requested id.
    (tmp_path / "single-user-chat" / "sessions").mkdir(parents=True)
    report = audit(tmp_path, "01NEVERPERSISTEDXXXXXX")
    assert report.found is False


@pytest.mark.unit
def test_audit_partial_session_still_reports(tmp_path: Path) -> None:
    """Only meta.json present — no memory, no files. Still ``found=True``."""
    sid = "01PARTIALSESSIONXXXXXXX"
    meta_dir = tmp_path / "single-user-chat" / "sessions" / sid
    meta_dir.mkdir(parents=True)
    (meta_dir / "meta.json").write_text(
        json.dumps({"id": sid, "title": "stub", "model": "openai:gpt-5.4-mini"})
    )
    report = audit(tmp_path, sid)
    assert report.found is True
    assert report.title == "stub"
    assert report.file_count == 0
    assert report.turn_count == 0
    assert report.total_tool_calls == 0


@pytest.mark.unit
def test_main_text_format_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = "01TESTSESSIONXXXXXXXXXX"
    _build_fake_session(tmp_path, sid, with_track_changes=False)
    code = main(["--session-id", sid, "--vfs-path", str(tmp_path), "--format", "text"])
    out = capsys.readouterr().out
    assert code == 0
    assert sid in out
    assert "contract.docx" in out
    assert "kaos-office-parse-docx" in out


@pytest.mark.unit
def test_main_json_format_is_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sid = "01TESTSESSIONXXXXXXXXXX"
    _build_fake_session(tmp_path, sid, with_track_changes=False)
    code = main(["--session-id", sid, "--vfs-path", str(tmp_path), "--format", "json"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["session_id"] == sid
    assert payload["file_count"] == 1
    assert payload["corpus_ever_attached"] is True
    assert payload["total_tool_calls"] == 2


@pytest.mark.unit
def test_main_missing_session_exits_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "single-user-chat" / "sessions").mkdir(parents=True)
    code = main(
        ["--session-id", "01DOESNOTEXIST00000000", "--vfs-path", str(tmp_path)]
    )
    err = capsys.readouterr().err
    assert code == 3
    assert "not found" in err


@pytest.mark.unit
def test_main_bad_vfs_path_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--session-id",
            "01ANYTHINGXXXXXXXXXX",
            "--vfs-path",
            "/nonexistent/path/that/should/never/exist",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "not a directory" in err
