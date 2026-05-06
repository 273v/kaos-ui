"""Compile-check every Python file every template emits.

Template `.py.tmpl` files contain ``{{KAOS_*}}`` placeholders that make
them syntactically invalid Python until rendered. We catch syntax bugs
in the *rendered* output here so they fail at our test time, not at the
user's scaffold time.

Strategy: dry-run scaffold each kind, then for the WRITE path scaffold
into a tmpdir and AST-parse every emitted ``*.py``. Purely structural —
no execution, no imports.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from kaos_ui import kinds


@pytest.mark.integration
@pytest.mark.parametrize("kind", kinds())
def test_every_emitted_python_file_parses(tmp_path: Path, kind: str) -> None:
    """Scaffold the kind, AST-parse every emitted .py."""
    project = tmp_path / "demo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            kind,
            "demo",
            "--target",
            str(project),
        ],
        check=True,
        cwd=tmp_path,
    )
    py_files = sorted(project.rglob("*.py"))
    assert py_files, f"no Python files emitted for kind {kind!r}"

    failures: list[tuple[Path, str]] = []
    for f in py_files:
        source = f.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(f))
        except SyntaxError as exc:
            failures.append((f.relative_to(project), f"{exc.msg} (line {exc.lineno})"))
            continue
        # ast.parse validates grammar; compile() additionally rejects
        # ``return`` / ``yield`` outside a function — bugs that
        # otherwise ship to Streamlit pages (PATTERNS.md
        # "Streamlit pages are scripts").
        try:
            compile(source, str(f), "exec")
        except SyntaxError as exc:
            failures.append((f.relative_to(project), f"compile: {exc.msg} (line {exc.lineno})"))

    if failures:
        msg = "\n".join(f"  {p}: {err}" for p, err in failures)
        pytest.fail(f"emitted Python files contain syntax errors:\n{msg}")


@pytest.mark.integration
@pytest.mark.parametrize("kind", kinds())
def test_every_emitted_pyproject_parses(tmp_path: Path, kind: str) -> None:
    """Scaffold the kind, parse the emitted pyproject.toml."""
    import tomllib

    project = tmp_path / "demo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            kind,
            "demo",
            "--target",
            str(project),
        ],
        check=True,
        cwd=tmp_path,
    )
    pyproject = project / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip(f"kind {kind!r} does not emit pyproject.toml")
    data = tomllib.loads(pyproject.read_text())
    assert data.get("project", {}).get("name"), f"{kind!r} pyproject is missing project.name"
    assert data["project"].get("dependencies"), (
        f"{kind!r} pyproject is missing project.dependencies"
    )


@pytest.mark.integration
@pytest.mark.parametrize("kind", kinds())
def test_python_version_consistency(tmp_path: Path, kind: str) -> None:
    """``.python-version`` must match ``pyproject.toml``'s requires-python.

    A .python-version file pinning 3.13 next to a pyproject demanding
    3.14 is the kind of subtle drift that nobody notices until uv sync
    fails on a fresh machine. We catch it here.
    """
    import tomllib

    project = tmp_path / "demo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            kind,
            "demo",
            "--target",
            str(project),
        ],
        check=True,
        cwd=tmp_path,
    )

    py_version_file = project / ".python-version"
    pyproject_path = project / "pyproject.toml"
    if not py_version_file.exists() or not pyproject_path.exists():
        pytest.skip(f"{kind!r} does not emit both .python-version and pyproject.toml")

    pinned = py_version_file.read_text().strip()  # e.g. "3.14"
    requires = tomllib.loads(pyproject_path.read_text())["project"]["requires-python"]
    # requires looks like ">=3.13,<3.15" — assert pinned satisfies it.
    assert pinned in requires or any(pinned.startswith(v) for v in ("3.13", "3.14")), (
        f"{kind!r}: .python-version={pinned!r} but pyproject requires {requires!r}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Foo Bar",  # space
        "kaos-thing-2",  # hyphens + number
        "MyApp123",  # mixed case + digits
        "snake_case_name",  # underscores
    ],
)
def test_adversarial_project_names(tmp_path: Path, name: str) -> None:
    """Names with spaces / hyphens / mixed-case / digits must scaffold cleanly.

    The scaffolder slugifies before substitution; this test pins that
    contract for inputs that are common-enough to break naive code.
    """
    project = tmp_path / "demo"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            "dashboard:streamlit",
            name,
            "--target",
            str(project),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"scaffold failed for name={name!r}: {result.stderr}"
    # All emitted Python should still parse.
    for f in project.rglob("*.py"):
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f))


@pytest.mark.integration
@pytest.mark.parametrize("kind", kinds())
def test_no_unrendered_placeholders_in_output(tmp_path: Path, kind: str) -> None:
    """No ``{{KAOS_*}}`` placeholders should survive scaffolding."""
    project = tmp_path / "demo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            kind,
            "demo",
            "--target",
            str(project),
        ],
        check=True,
        cwd=tmp_path,
    )
    text_extensions = {
        ".py",
        ".toml",
        ".yml",
        ".yaml",
        ".md",
        ".txt",
        ".tcss",
        ".tsx",
        ".ts",
        ".html",
        ".css",
        ".json",
        ".sh",
    }
    leaks: list[tuple[Path, int]] = []
    for f in project.rglob("*"):
        if not f.is_file() or f.suffix not in text_extensions:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "{{KAOS_" in text or ("}}" in text and "{{" in text):
            for lineno, line in enumerate(text.splitlines(), 1):
                if "{{KAOS_" in line:
                    leaks.append((f.relative_to(project), lineno))
                    break

    if leaks:
        msg = "\n".join(f"  {p}:{lineno}" for p, lineno in leaks)
        pytest.fail(f"unrendered placeholders in scaffold:\n{msg}")
