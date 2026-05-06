"""Scaffolder: materialize a template kind into a target directory.

Ported from ``kaos-mcp/kaos_mcp/management/scaffold.py`` with the public
surface preserved. Variable substitution uses ``{{KAOS_*}}`` placeholders
in file contents and paths; binary files (images, fonts) bypass
substitution to avoid corruption.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from kaos_core.logging import get_logger

from kaos_ui.exceptions import ScaffoldError, TargetExistsError
from kaos_ui.manifest import TEMPLATES, get_manifest, resolve_kind

logger = get_logger("kaos.ui.scaffolder")

_SKIP_SUBSTITUTE = {".png", ".jpg", ".ico", ".woff", ".woff2", ".ttf", ".eot"}


def _slugify(name: str) -> str:
    """Convert a project name to a Python-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    return slug.strip("_")


def _build_variables(name: str, kind: str) -> dict[str, str]:
    slug = _slugify(name)
    # NPM scope names allow hyphens but not underscores; produce a
    # parallel hyphenated variant for use as an npm scope or workspace
    # package-name (the underscored ``KAOS_PYTHON_MODULE`` is for
    # Python packages).
    npm_slug = re.sub(r"[^a-z0-9-]+", "-", name.lower().strip()).strip("-")
    return {
        "KAOS_PROJECT_NAME": name,
        "KAOS_PROJECT_SLUG": slug,
        "KAOS_PYTHON_MODULE": slug.replace("-", "_"),
        "KAOS_NPM_SLUG": npm_slug,
        "KAOS_PYTHON_VERSION": "3.14",
        "KAOS_NODE_VERSION": "24",
        "KAOS_TEMPLATE": kind,
    }


def _substitute(content: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def _render_template_path(path: Path, variables: dict[str, str]) -> Path:
    rendered = _substitute(str(path), variables)
    return Path(rendered.removesuffix(".tmpl"))


def _copy_template(
    template_dir: Path,
    target_dir: Path,
    variables: dict[str, str],
    exclude_prefixes: list[str] | None = None,
) -> list[str]:
    created: list[str] = []
    excludes = exclude_prefixes or []

    for src in sorted(template_dir.rglob("*")):
        if src.is_dir():
            continue
        if src.name == "__pycache__" or ".pyc" in src.name:
            continue

        rel = src.relative_to(template_dir)
        rel_posix = rel.as_posix()
        if any(rel_posix.startswith(prefix) for prefix in excludes):
            continue

        rendered_rel = _render_template_path(rel, variables)
        dst = target_dir / rendered_rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.suffix in _SKIP_SUBSTITUTE:
            shutil.copy2(src, dst)
        else:
            try:
                content = src.read_text(encoding="utf-8")
                content = _substitute(content, variables)
                dst.write_text(content, encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(src, dst)

        if src.stat().st_mode & 0o111:
            dst.chmod(dst.stat().st_mode | 0o111)

        created.append(rendered_rel.as_posix())

    return created


def scaffold(
    template: str,
    name: str,
    target_dir: Path | None = None,
    *,
    ssr: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Materialize a template kind into a target directory.

    Args:
        template: Template kind. Accepts canonical ``namespace:variant``
            (``web:spa``) or legacy single-segment names (``app``).
        name: Project name; used for the slug and substitution.
        target_dir: Where to create the project. Defaults to ``./<name>``.
        ssr: For ``web:spa``, use TanStack Start (SSR) instead of SPA.
        dry_run: If True, return the file list without writing.

    Returns:
        Dict with ``template``, ``name``, ``target``, ``files`` keys.

    Raises:
        UnknownTemplateError: ``template`` is not a registered kind.
        TargetExistsError: ``target_dir`` exists and is not empty.
        ScaffoldError: any I/O failure during materialization.
    """
    canonical = resolve_kind(template)
    manifest = get_manifest(canonical)
    template_dir = manifest.template_dir

    if not template_dir.is_dir():
        msg = (
            f"Template directory not found: {template_dir}\n"
            f"How to fix: confirm the kaos-ui package is installed correctly.\n"
            f"Alternative: run `kaos-ui list` to see registered kinds."
        )
        raise ScaffoldError(msg)

    if target_dir is None:
        target_dir = Path.cwd() / name

    variables = _build_variables(name, canonical)

    exclude_prefixes: list[str] = []
    if canonical == "web:spa":
        exclude_prefixes.append("apps/spa/" if ssr else "apps/ssr/")

    if dry_run:
        files: list[str] = []
        for src in sorted(template_dir.rglob("*")):
            if src.is_dir() or src.name == "__pycache__":
                continue
            rel = src.relative_to(template_dir)
            rel_posix = rel.as_posix()
            if any(rel_posix.startswith(p) for p in exclude_prefixes):
                continue
            rendered_rel = _render_template_path(rel, variables)
            files.append(rendered_rel.as_posix())
        return {
            "template": canonical,
            "name": name,
            "target": str(target_dir),
            "files": files,
            "ssr": ssr if canonical == "web:spa" else None,
            "dry_run": True,
        }

    if target_dir.exists() and any(target_dir.iterdir()):
        msg = (
            f"Target directory already exists and is not empty: {target_dir}\n"
            f"How to fix: pick a different --target, or remove the existing directory.\n"
            f"Alternative: pass --dry-run to inspect without writing."
        )
        raise TargetExistsError(msg)

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        files = _copy_template(template_dir, target_dir, variables, exclude_prefixes)
    except OSError as exc:
        msg = (
            f"Failed to materialize template into {target_dir}: {exc}\n"
            f"How to fix: confirm the target directory is writable and disk is not full.\n"
            f"Alternative: pass --dry-run to validate the template before writing."
        )
        raise ScaffoldError(msg) from exc

    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "init", str(target_dir)],
            capture_output=True,
            timeout=10,
            check=False,
        )

    logger.info(
        "scaffolded template",
        extra={
            "template_kind": canonical,
            "project_name": name,
            "target": str(target_dir),
            "file_count": len(files),
        },
    )

    return {
        "template": canonical,
        "name": name,
        "target": str(target_dir),
        "files": files,
        "dry_run": False,
    }


def list_templates() -> dict[str, str]:
    """Return ``{kind: description}``. Re-exported for compat with kaos-mcp's old API."""
    return dict(TEMPLATES)


__all__ = ["TEMPLATES", "list_templates", "scaffold"]
