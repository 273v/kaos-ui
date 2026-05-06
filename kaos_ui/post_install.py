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


def run(steps: list[PostInstallStep], cwd: Path) -> list[dict[str, object]]:
    """Execute ``steps`` sequentially in ``cwd``. Returns one record per step."""
    results: list[dict[str, object]] = []
    for step in steps:
        argv = shlex.split(step.command)
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        except FileNotFoundError as exc:
            if step.optional:
                results.append({"command": step.command, "status": "skipped", "reason": str(exc)})
                continue
            msg = (
                f"Required tool not found while running {step.command!r}: {exc}\n"
                f"How to fix: install the missing tool — `kaos doctor` will tell you which.\n"
                f"Alternative: pass --no-install to skip post-install steps."
            )
            raise PostInstallError(msg) from exc

        record: dict[str, object] = {
            "command": step.command,
            "status": "ok" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-500:] if completed.stdout else "",
            "stderr_tail": completed.stderr[-500:] if completed.stderr else "",
        }
        results.append(record)

        if completed.returncode != 0 and not step.optional:
            msg = (
                f"Post-install step failed: {step.command!r} exited {completed.returncode}\n"
                f"How to fix: read the stderr tail above and re-run manually inside the project.\n"
                f"Alternative: re-run scaffold with --no-install and execute steps yourself."
            )
            logger.error("post-install failure", extra=record)
            raise PostInstallError(msg)

    return results
