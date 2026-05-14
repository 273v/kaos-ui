"""post_install.run() must execute `cd X && y` chains.

`shlex.split` alone treats `&&` as a positional arg to `cd`. The chain
parser splits on `&&` and tracks cwd per sub-step so manifest commands
like `cd backend && uv sync && uv run pre-commit install` work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_ui.exceptions import PostInstallError
from kaos_ui.post_install import PostInstallStep, _parse_chained, run


def test_parse_chained_splits_cd_chain(tmp_path: Path) -> None:
    sub = tmp_path / "backend"
    sub.mkdir()
    chain = _parse_chained("cd backend && uv sync && echo hi", tmp_path)
    assert len(chain) == 2
    (argv1, cwd1), (argv2, cwd2) = chain
    assert argv1 == ["uv", "sync"]
    assert cwd1 == sub.resolve()
    assert argv2 == ["echo", "hi"]
    assert cwd2 == sub.resolve()


def test_parse_chained_rejects_unknown_cd_shape(tmp_path: Path) -> None:
    with pytest.raises(PostInstallError, match="must take exactly one argument"):
        _parse_chained("cd && echo hi", tmp_path)


def test_parse_chained_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(PostInstallError, match="directory does not exist"):
        _parse_chained("cd nope && echo hi", tmp_path)


def test_parse_chained_rejects_shell_builtins(tmp_path: Path) -> None:
    with pytest.raises(PostInstallError, match="shell builtin not allowed"):
        _parse_chained("export FOO=bar && echo hi", tmp_path)


def test_run_executes_chain_in_correct_cwd(tmp_path: Path) -> None:
    """End-to-end — run() actually executes a chained command."""
    sub = tmp_path / "child"
    sub.mkdir()
    target = sub / "marker"

    steps = [
        PostInstallStep(
            command=f"cd child && touch {target.name}",
            description="touch marker in child",
        ),
    ]
    records = run(steps, cwd=tmp_path)
    assert len(records) == 1
    assert records[0]["status"] == "ok"
    assert target.exists()
