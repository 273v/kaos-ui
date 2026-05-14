"""CLI smoke + JSON-envelope coverage.

Every subcommand has a happy-path test and a --json envelope test.
Errors raise SystemExit; tests assert exit code + stderr content.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from kaos_ui.cli import main


def _run(argv: list[str]) -> None:
    main(argv)


def test_no_command_prints_help_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        _run([])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "scaffold, configure, and validate" in captured.out.lower()


def test_list_command_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    _run(["list"])
    captured = capsys.readouterr()
    assert "Available templates:" in captured.out
    assert "web:spa" in captured.out


def test_list_command_json_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    _run(["list", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "list"
    kinds = {t["kind"] for t in payload["templates"]}
    assert "web:spa" in kinds


def test_info_command_human(capsys: pytest.CaptureFixture[str]) -> None:
    _run(["info", "web:spa"])
    captured = capsys.readouterr()
    assert "web:spa" in captured.out


def test_info_command_json(capsys: pytest.CaptureFixture[str]) -> None:
    _run(["info", "workflow", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "info"
    assert payload["kind"] == "workflow"


def test_info_unknown_kind_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(["info", "no-such-kind"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_new_dry_run_does_not_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "demo"
    _run(["new", "workflow", "demo", "--target", str(out), "--dry-run"])
    captured = capsys.readouterr()
    assert "Would create" in captured.out
    assert not out.exists()


def test_new_command_writes_and_prints_next_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "demo"
    _run(["new", "workflow", "demo", "--target", str(out)])
    assert out.is_dir()
    captured = capsys.readouterr()
    assert "Created" in captured.out


def test_new_command_json_envelope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "demo"
    _run(["new", "workflow", "demo", "--target", str(out), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "new"
    assert payload["template"] == "workflow"
    assert "files" in payload


def test_new_unknown_kind_exits_with_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "demo"
    with pytest.raises(SystemExit) as exc:
        _run(["new", "no-such-kind", "demo", "--target", str(out)])
    assert exc.value.code == 1
    assert "Error:" in capsys.readouterr().err


def test_doctor_on_empty_dir_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Doctor expects a real path; on an empty tmp_path it succeeds with no
    # findings or some informational ones (no SystemExit unless ok=False).
    try:
        _run(["doctor", str(tmp_path)])
    except SystemExit as exc:
        # If doctor flags issues, exit code 1 is correct; either outcome
        # confirms the handler executed.
        assert exc.code in (0, 1)
    captured = capsys.readouterr()
    assert "doctor:" in captured.out


def test_doctor_json_envelope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with contextlib.suppress(SystemExit):
        _run(["doctor", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "doctor"
    assert "findings" in payload
