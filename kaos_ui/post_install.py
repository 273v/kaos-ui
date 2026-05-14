"""Post-install hooks for scaffolded projects.

Phase 0 ships a minimal command-builder; Phase 1 wires it into the CLI.
The split exists so the MCP tool can return the planned commands as a
structured manifest without actually executing them — the agent decides
whether to run, skip, or modify the steps.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kaos_core.logging import get_logger

from kaos_ui.exceptions import PostInstallError
from kaos_ui.manifest import get_manifest

logger = get_logger("kaos.ui.post_install")


@dataclass(frozen=True, slots=True)
class PostInstallStep:
    """One command to run inside the scaffolded project root."""

    command: str
    description: str
    optional: bool = False


def plan(kind: str) -> list[PostInstallStep]:
    """Return the post-install commands declared by the manifest for ``kind``."""
    manifest = get_manifest(kind)
    return [
        PostInstallStep(command=cmd, description=f"running {cmd}", optional=False)
        for cmd in manifest.post_install
    ]


def _parse_chained(command: str, base_cwd: Path) -> list[tuple[list[str], Path]]:
    """Split a `cd X && y && z` chain into (argv, cwd) pairs.

    Hand-parses the `cd` + `&&` chain so manifest commands like
    `cd backend && uv sync && uv run pre-commit install` execute as
    three steps with the right cwd, without enabling a shell — which
    would invite injection from manifest-author-controlled strings.

    Returns one (argv, cwd) tuple per chained command. Raises
    PostInstallError on anything we don't recognize.
    """
    parts = [p.strip() for p in command.split("&&")]
    cwd = base_cwd
    out: list[tuple[list[str], Path]] = []
    for part in parts:
        if not part:
            continue
        argv = shlex.split(part)
        if not argv:
            continue
        # Handle `cd <dir>` — mutates cwd for subsequent steps.
        if argv[0] == "cd":
            if len(argv) != 2:
                raise PostInstallError(
                    f"unsupported post-install shape: {part!r} — "
                    "`cd` must take exactly one argument."
                )
            target = (cwd / argv[1]).resolve()
            if not target.is_dir():
                raise PostInstallError(
                    f"post-install `cd {argv[1]}` failed: directory does not exist at {target}."
                )
            cwd = target
            continue
        # Refuse other shell-builtin-looking commands the no-shell
        # path can't run. `export`, `set`, `source`, `.`, etc.
        if argv[0] in {"export", "set", "source", ".", "if", "fi", "for", "while"}:
            raise PostInstallError(
                f"unsupported post-install shape: {part!r} — shell builtin not allowed."
            )
        out.append((argv, cwd))
    return out


def run(steps: list[PostInstallStep], cwd: Path) -> list[dict[str, object]]:
    """Execute ``steps`` sequentially in ``cwd``.

    Each step may be a chained `cd X && y && z` command (manifest
    authors write these for ergonomics). We parse the chain ourselves
    rather than enabling `shell=True` so manifest strings can't smuggle
    arbitrary shell. Returns one record per CHAINED step.
    """
    results: list[dict[str, object]] = []
    for step in steps:
        try:
            chain = _parse_chained(step.command, cwd)
        except PostInstallError as exc:
            if step.optional:
                results.append(
                    {"command": step.command, "status": "skipped", "reason": str(exc)},
                )
                continue
            raise

        if not chain:
            results.append({"command": step.command, "status": "noop"})
            continue

        # Execute every (argv, cwd) sub-command; a single failure aborts
        # the rest of the chain.
        chain_record: dict[str, object] = {
            "command": step.command,
            "status": "ok",
            "exit_code": 0,
            "stdout_tail": "",
            "stderr_tail": "",
        }
        for argv, sub_cwd in chain:
            try:
                completed = subprocess.run(
                    argv,
                    cwd=str(sub_cwd),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=600,
                )
            except FileNotFoundError as exc:
                if step.optional:
                    chain_record["status"] = "skipped"
                    chain_record["reason"] = str(exc)
                    break
                msg = (
                    f"Required tool not found while running {' '.join(argv)!r}: {exc}\n"
                    "How to fix: install the missing tool — `kaos doctor` will tell you which.\n"
                    "Alternative: pass --no-install to skip post-install steps."
                )
                raise PostInstallError(msg) from exc

            chain_record["exit_code"] = completed.returncode
            chain_record["stdout_tail"] = (completed.stdout or "")[-500:]
            chain_record["stderr_tail"] = (completed.stderr or "")[-500:]

            if completed.returncode != 0:
                chain_record["status"] = "failed"
                if not step.optional:
                    logger.error("post-install failure", extra=chain_record)
                    results.append(chain_record)
                    raise PostInstallError(
                        f"Post-install step failed: {' '.join(argv)!r} exited "
                        f"{completed.returncode}\n"
                        "How to fix: read the stderr tail above and re-run manually "
                        "inside the project.\n"
                        "Alternative: re-run scaffold with --no-install and execute "
                        "steps yourself."
                    )
                break

        results.append(chain_record)

    return results
