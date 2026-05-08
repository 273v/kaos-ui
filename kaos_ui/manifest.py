"""Template registry for kaos-ui.

A ``TemplateManifest`` describes one scaffold kind: its identifier, the
language stack it produces, the on-disk directory holding the template,
required environment variables, and the post-install commands needed to
get the generated project to a runnable state.

The registry is the single source of truth used by both the CLI and the
MCP tools. Phase 0 ships only the lifted-and-shifted templates; Phase 1
adds TUI and desktop entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kaos_ui.exceptions import UnknownTemplateError

_TEMPLATES_ROOT = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class TemplateManifest:
    """Describes one template kind."""

    kind: str
    description: str
    stack: str
    template_dir: Path
    required_env: tuple[str, ...] = ()
    post_install: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)


_REGISTRY: dict[str, TemplateManifest] = {
    "web:api": TemplateManifest(
        kind="web:api",
        description="FastAPI backend with KAOS integration",
        stack="Python 3.14 + FastAPI + uvicorn",
        template_dir=_TEMPLATES_ROOT / "web" / "api",
        post_install=("uv sync",),
        next_steps=("cd {name}", "uv run fastapi dev"),
        tags=("backend", "api"),
    ),
    "web:spa": TemplateManifest(
        kind="web:spa",
        description=(
            "Fullstack: Vite + React + Tailwind v4 + shadcn + FastAPI + Caddy"
            " + Docker, kaos-agents wired"
        ),
        stack=(
            "Vite 6 + React 19 + TanStack Router/Query + Tailwind v4 + Biome + FastAPI on kaos-core"
        ),
        template_dir=_TEMPLATES_ROOT / "web" / "spa",
        required_env=("APP_AUTH_TOKEN",),
        post_install=("pnpm install", "cd backend && uv sync && uv run pre-commit install"),
        next_steps=(
            "cd {name}",
            "cp .env.example .env  # then set APP_AUTH_TOKEN + your LLM API key",
            "make install",
            "make doctor",
            "make dev      # backend on :8000, vite on :5173",
        ),
        tags=("fullstack", "web", "agentic"),
    ),
    "dashboard:streamlit": TemplateManifest(
        kind="dashboard:streamlit",
        description="Streamlit dashboard with kaos-agents chat, uploads, search, browse",
        stack="Python 3.14 + Streamlit + kaos-agents",
        template_dir=_TEMPLATES_ROOT / "dashboard" / "streamlit",
        required_env=("APP_AUTH_TOKEN",),
        post_install=("uv sync", "uv run pre-commit install"),
        next_steps=(
            "cd {name}",
            "cp .env.example .env  # then set APP_AUTH_TOKEN + your LLM API key",
            "make doctor",
            "make dev",
        ),
        tags=("dashboard", "data", "agentic"),
    ),
    "tui:textual": TemplateManifest(
        kind="tui:textual",
        description="Textual terminal UI with kaos-agents chat, document browser, settings",
        stack="Python 3.14 + Textual + kaos-agents",
        template_dir=_TEMPLATES_ROOT / "tui" / "textual",
        required_env=("ANTHROPIC_API_KEY",),  # or another provider key
        post_install=("uv sync", "uv run pre-commit install"),
        next_steps=(
            "cd {name}",
            "cp .env.example .env  # then set your LLM API key",
            "make doctor",
            "make dev",
        ),
        tags=("tui", "terminal", "agentic"),
    ),
    "module": TemplateManifest(
        kind="module",
        description="KAOS module package (tools, CLI, serve, tests)",
        stack="Python 3.14 + KAOS module conventions",
        template_dir=_TEMPLATES_ROOT / "module",
        post_install=("uv sync",),
        next_steps=("cd {name}", "uv sync", "uv run pytest tests/ -v"),
        tags=("module", "package"),
    ),
    "workflow": TemplateManifest(
        kind="workflow",
        description="Single-file Python script with KAOS imports",
        stack="Python 3.14",
        template_dir=_TEMPLATES_ROOT / "workflow",
        post_install=("uv sync",),
        next_steps=("cd {name}", "uv run python main.py"),
        tags=("workflow", "script"),
    ),
    # Phase 1 placeholders — directories exist but templates land in the next phase.
    # Listing them here as "coming-soon" would mislead the CLI; entries are added
    # at the end of Phase 1 when the templates ship.
}


def list_templates() -> list[TemplateManifest]:
    """Return all registered manifests, sorted by kind."""
    return sorted(_REGISTRY.values(), key=lambda m: m.kind)


def get_manifest(kind: str) -> TemplateManifest:
    """Look up a manifest by kind. Raises ``UnknownTemplateError`` if absent."""
    canonical = resolve_kind(kind)
    if canonical not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        msg = (
            f"Unknown template kind: {kind!r}.\n"
            f"How to fix: pass one of {available}.\n"
            f"Alternative: run `kaos-ui list` to see all kinds."
        )
        raise UnknownTemplateError(msg)
    return _REGISTRY[canonical]


def register_template(manifest: TemplateManifest) -> None:
    """Register a template manifest with the global registry.

    Extension point for downstream packages that want to expose their
    own scaffolds through the same CLI and MCP surface as kaos-ui's
    built-in kinds.
    """
    _REGISTRY[manifest.kind] = manifest
    TEMPLATES[manifest.kind] = manifest.description


def register_alias(legacy: str, canonical: str) -> None:
    """Register a legacy single-segment kind alias."""
    _LEGACY_ALIASES[legacy] = canonical


def kinds() -> list[str]:
    """Return the list of registered kind identifiers."""
    return sorted(_REGISTRY)


# Compat: existing callers (kaos-mcp shim) expect a flat ``TEMPLATES`` dict.
TEMPLATES: dict[str, str] = {m.kind: m.description for m in _REGISTRY.values()}

# Compat: legacy single-segment kind names used by the old ``kaos new`` CLI.
# ``kaos new app demo`` → ``web:spa``; ``kaos new dashboard demo`` → ``dashboard:streamlit``;
# ``kaos new api demo`` → ``web:api``. Keeps Phase 0 backward-compatible.
_LEGACY_ALIASES: dict[str, str] = {
    "api": "web:api",
    "app": "web:spa",
    "dashboard": "dashboard:streamlit",
    "tui": "tui:textual",
}


def resolve_kind(kind: str) -> str:
    """Resolve legacy single-segment kinds to canonical ``namespace:variant`` form."""
    return _LEGACY_ALIASES.get(kind, kind)
