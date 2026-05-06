"""Doctor for scaffolded projects.

Phase 0 ships the data shapes and a minimal real check (env file
presence). Phase 2 fleshes out the full check matrix and wires this
into the MCP tool. The MCP tool and the CLI both call ``run_doctor``
so there's a single source of truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Finding:
    """One health-check finding. Shape matches the agent-friendly error contract."""

    severity: Severity
    what: str
    how_to_fix: str
    alternative_tool: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Full report for a scaffolded project."""

    path: str
    ok: bool
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "ok": self.ok,
            "findings": [asdict(f) for f in self.findings],
        }


def run_doctor(path: Path) -> DoctorReport:
    """Run health checks against a scaffolded project rooted at ``path``."""
    findings: list[Finding] = []

    if not path.exists():
        findings.append(
            Finding(
                severity="error",
                what=f"Path does not exist: {path}",
                how_to_fix="Pass an existing directory containing a kaos-ui scaffold.",
                alternative_tool="kaos-ui new <kind> <name>",
            )
        )
        return DoctorReport(path=str(path), ok=False, findings=findings)

    if not path.is_dir():
        findings.append(
            Finding(
                severity="error",
                what=f"Path is not a directory: {path}",
                how_to_fix="Pass the project root, not a file.",
            )
        )
        return DoctorReport(path=str(path), ok=False, findings=findings)

    env_example = path / ".env.example"
    env_real = path / ".env"
    if env_example.exists() and not env_real.exists():
        findings.append(
            Finding(
                severity="warning",
                what=".env file is missing; .env.example exists",
                how_to_fix=f"Copy {env_example.name} to .env and fill in values.",
            )
        )

    gitignore = path / ".gitignore"
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8", errors="replace")
        if ".env" not in text:
            findings.append(
                Finding(
                    severity="error",
                    what=".gitignore does not exclude .env",
                    how_to_fix="Add `.env` to .gitignore before committing secrets.",
                )
            )

    ok = not any(f.severity == "error" for f in findings)
    return DoctorReport(path=str(path), ok=ok, findings=findings)
