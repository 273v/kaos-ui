"""Doctor for scaffolded projects.

Phase 0 ships the data shapes and a minimal real check (env file
presence). Phase 2 fleshes out the full check matrix and wires this
into the MCP tool. The MCP tool and the CLI both call ``run_doctor``
so there's a single source of truth.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, cast

Severity = Literal["info", "warning", "error"]

MIN_HARDENED_PNPM_VERSION = "11.1.0"
REQUIRED_PNPM_SETTINGS: dict[str, object] = {
    "minimumReleaseAge": 4320,
    "minimumReleaseAgeStrict": False,
    "minimumReleaseAgeIgnoreMissingTime": True,
    "resolutionMode": "highest",
    "blockExoticSubdeps": True,
    "strictDepBuilds": True,
    "dangerouslyAllowAllBuilds": False,
    "savePrefix": "",
}
REQUIRED_ALLOW_BUILDS = {"esbuild": True}
_SUSPICIOUS_REL_PATHS = {
    ".claude/setup.mjs",
    ".vscode/setup.mjs",
}
_SUSPICIOUS_NAMES = {
    "router_init.js",
}
_SUSPICIOUS_LOCK_PATTERNS = (
    "@tanstack/setup",
    "router_init.js",
    ".claude/setup.mjs",
    ".vscode/setup.mjs",
)
_SKIP_WALK_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pnpm-store",
    "dist",
    "build",
    ".next",
    ".vite",
}


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


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or "0")


def _version_lt(current: str, minimum: str) -> bool:
    parsed_current = _parse_semver(current)
    parsed_minimum = _parse_semver(minimum)
    if parsed_current is None or parsed_minimum is None:
        return True
    return parsed_current < parsed_minimum


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if value in {'""', "''"}:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _read_workspace_settings(path: Path) -> dict[str, object]:
    """Read the small root-level pnpm-workspace.yaml shape KAOS generates."""
    settings: dict[str, object] = {}
    current_map: str | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                settings[key] = {}
                current_map = key
            else:
                settings[key] = _parse_scalar(value)
                current_map = None
            continue
        if current_map and line.startswith("  ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            child = settings.get(current_map)
            if isinstance(child, dict):
                child = cast(dict[str, object], child)
                child[key.strip()] = _parse_scalar(value)
    return settings


def _check_pnpm_binary(findings: list[Finding]) -> None:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        findings.append(
            Finding(
                severity="warning",
                what="pnpm is not available on PATH",
                how_to_fix="Run `kaos setup env` to activate pnpm 11.1+ through Corepack.",
            )
        )
        return
    try:
        result = subprocess.run(
            [pnpm, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        findings.append(
            Finding(
                severity="warning",
                what="pnpm is installed but its version could not be checked",
                how_to_fix="Run `kaos setup env` to activate pnpm 11.1+ through Corepack.",
            )
        )
        return
    version = result.stdout.strip() or result.stderr.strip()
    if _version_lt(version, MIN_HARDENED_PNPM_VERSION):
        findings.append(
            Finding(
                severity="warning",
                what=f"pnpm {version} is older than KAOS minimum {MIN_HARDENED_PNPM_VERSION}",
                how_to_fix="Run `kaos setup env` so Corepack activates the hardened pnpm baseline.",
            )
        )


def _check_package_manager(path: Path, findings: list[Finding]) -> None:
    package_json = path / "package.json"
    if not package_json.exists():
        findings.append(
            Finding(
                severity="error",
                what="package.json is missing from this pnpm workspace",
                how_to_fix="Restore the root package.json generated by `kaos-ui new web:spa`.",
            )
        )
        return
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        findings.append(
            Finding(
                severity="error",
                what="package.json is not valid JSON",
                how_to_fix="Fix package.json syntax, then rerun `kaos-ui doctor .`.",
            )
        )
        return
    package_manager = data.get("packageManager")
    if not isinstance(package_manager, str) or not package_manager:
        findings.append(
            Finding(
                severity="error",
                what="package.json is missing packageManager",
                how_to_fix=f'Add `"packageManager": "pnpm@{MIN_HARDENED_PNPM_VERSION}"`.',
            )
        )
        return
    if not package_manager.startswith("pnpm@"):
        findings.append(
            Finding(
                severity="error",
                what=f"packageManager is not pnpm: {package_manager}",
                how_to_fix=f'Set packageManager to `"pnpm@{MIN_HARDENED_PNPM_VERSION}"`.',
            )
        )
        return
    version = package_manager.removeprefix("pnpm@")
    if _version_lt(version, MIN_HARDENED_PNPM_VERSION):
        findings.append(
            Finding(
                severity="error",
                what=(
                    f"packageManager pins pnpm {version}, below KAOS minimum "
                    f"{MIN_HARDENED_PNPM_VERSION}"
                ),
                how_to_fix=f'Set packageManager to `"pnpm@{MIN_HARDENED_PNPM_VERSION}"`.',
            )
        )


def _check_pnpm_workspace(path: Path, findings: list[Finding]) -> None:
    workspace = path / "pnpm-workspace.yaml"
    if not workspace.exists():
        findings.append(
            Finding(
                severity="error",
                what="pnpm-workspace.yaml is missing",
                how_to_fix="Restore the hardened pnpm-workspace.yaml generated by kaos-ui.",
            )
        )
        return
    settings = _read_workspace_settings(workspace)
    for key, expected in REQUIRED_PNPM_SETTINGS.items():
        actual = settings.get(key)
        if actual != expected:
            findings.append(
                Finding(
                    severity="error",
                    what=f"pnpm-workspace.yaml has weak or missing `{key}` setting",
                    how_to_fix=f"Set `{key}: {expected}` in pnpm-workspace.yaml.",
                )
            )
    allow_builds = settings.get("allowBuilds")
    if allow_builds != REQUIRED_ALLOW_BUILDS:
        findings.append(
            Finding(
                severity="error",
                what="pnpm-workspace.yaml is missing the reviewed build-script allowlist",
                how_to_fix=(
                    "Set `allowBuilds.esbuild: true` and do not enable all dependency builds."
                ),
            )
        )


def _check_lockfile(path: Path, findings: list[Finding]) -> None:
    lockfile = path / "pnpm-lock.yaml"
    if not lockfile.exists():
        findings.append(
            Finding(
                severity="warning",
                what="pnpm-lock.yaml is missing",
                how_to_fix=(
                    "Run `pnpm install`, review the dependency build prompts, and commit "
                    "pnpm-lock.yaml."
                ),
            )
        )


def _iter_project_files(path: Path) -> list[Path]:
    files: list[Path] = []
    stack = [path]
    while stack:
        current = stack.pop()
        for child in current.iterdir():
            if child.is_dir():
                if child.name not in _SKIP_WALK_DIRS:
                    stack.append(child)
            else:
                files.append(child)
    return files


def _check_suspicious_js_artifacts(path: Path, findings: list[Finding]) -> None:
    for file_path in _iter_project_files(path):
        rel = file_path.relative_to(path).as_posix()
        if rel in _SUSPICIOUS_REL_PATHS or file_path.name in _SUSPICIOUS_NAMES:
            findings.append(
                Finding(
                    severity="error",
                    what=f"Suspicious npm worm setup artifact found: {rel}",
                    how_to_fix=(
                        "Remove the file, reinstall dependencies from a reviewed lockfile, "
                        "and rotate exposed tokens."
                    ),
                )
            )
    lockfile = path / "pnpm-lock.yaml"
    if lockfile.exists():
        text = lockfile.read_text(encoding="utf-8", errors="replace")
        for pattern in _SUSPICIOUS_LOCK_PATTERNS:
            if pattern in text:
                findings.append(
                    Finding(
                        severity="error",
                        what=(
                            f"pnpm-lock.yaml contains suspicious package/artifact marker: {pattern}"
                        ),
                        how_to_fix=(
                            "Regenerate the lockfile after removing the suspicious dependency "
                            "and rotate exposed tokens."
                        ),
                    )
                )


def _check_node_workspace(path: Path, findings: list[Finding]) -> None:
    _check_pnpm_binary(findings)
    _check_package_manager(path, findings)
    _check_pnpm_workspace(path, findings)
    _check_lockfile(path, findings)
    _check_suspicious_js_artifacts(path, findings)


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

    if (path / "pnpm-workspace.yaml").exists() or (path / "package.json").exists():
        _check_node_workspace(path, findings)

    ok = not any(f.severity == "error" for f in findings)
    return DoctorReport(path=str(path), ok=ok, findings=findings)
