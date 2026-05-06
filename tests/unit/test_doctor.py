"""Doctor tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_ui.doctor import run_doctor


@pytest.mark.unit
def test_missing_path_is_error(tmp_path: Path) -> None:
    report = run_doctor(tmp_path / "does-not-exist")
    assert not report.ok
    assert any("does not exist" in f.what for f in report.findings)


@pytest.mark.unit
def test_clean_scaffold_passes(tmp_project_root: Path) -> None:
    (tmp_project_root / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    (tmp_project_root / ".env").write_text("FOO=secret\n", encoding="utf-8")
    (tmp_project_root / ".gitignore").write_text(".env\n", encoding="utf-8")

    report = run_doctor(tmp_project_root)
    assert report.ok
    assert all(f.severity != "error" for f in report.findings)


@pytest.mark.unit
def test_missing_env_is_warning(tmp_project_root: Path) -> None:
    (tmp_project_root / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    (tmp_project_root / ".gitignore").write_text(".env\n", encoding="utf-8")

    report = run_doctor(tmp_project_root)
    # warnings don't flip ok=False
    assert report.ok
    assert any(
        f.severity == "warning" and ".env file is missing" in f.what for f in report.findings
    )


@pytest.mark.unit
def test_gitignore_missing_env_is_error(tmp_project_root: Path) -> None:
    (tmp_project_root / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    (tmp_project_root / ".env").write_text("FOO=secret\n", encoding="utf-8")
    (tmp_project_root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    report = run_doctor(tmp_project_root)
    assert not report.ok
    assert any(
        f.severity == "error" and ".gitignore does not exclude .env" in f.what
        for f in report.findings
    )


@pytest.mark.unit
def test_findings_have_agent_friendly_shape(tmp_project_root: Path) -> None:
    (tmp_project_root / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    (tmp_project_root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

    report = run_doctor(tmp_project_root)
    for finding in report.findings:
        # Every finding has what + how_to_fix; alternative is optional.
        assert finding.what
        assert finding.how_to_fix
