"""Application settings for the Single-User Chat backend.

Owns ONLY the example-specific defaults (`APP_*` env vars). The
kaos-agents HTTP API has its own settings class
(``KaosAgentsApiSettings``) that reads ``KAOS_AGENTS_API_API_*``
env vars — we don't redeclare those here.

See docs/ARCHITECTURE.md § 4.2 and docs/PATTERNS.md P-001 for the
naming traps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from kaos_core.config import ModuleSettings
from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from app.exceptions import SettingsError

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's questions clearly. "
    "Use the available tools when they would help. When you cite a "
    "document, name it explicitly."
)


class AppSettings(ModuleSettings):
    """Configuration for the Single-User Chat backend.

    Resolution order (per KAOS hierarchy): explicit kwargs →
    ``APP_*`` env vars → ``.env`` file → defaults.
    """

    # Environment shape
    env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # VFS — where our session metadata sidecar lives. The path is also
    # used by kaos-core's default VFS, so this overrides both layers.
    vfs_path: Path = Path(".kaos-vfs")

    # Per-session defaults (overridable via the SPA's settings drawer).
    default_model: str = "anthropic:claude-haiku-4-5"
    default_system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    default_tools_enabled: bool = True

    # Per-turn budget cap (USD). Threaded into MessageRequest.max_cost_usd.
    turn_budget_usd: float = 0.50

    # File-upload pipeline (P1-1).
    # Max accepted bytes per upload — 25 MiB by default. Large enough for
    # a typical SEC filing or a deal-room PDF, small enough to keep the
    # sync-parser path responsive.
    max_upload_bytes: int = 25 * 1024 * 1024
    # Extensions we dispatch a parser for. XLSX intentionally absent —
    # kaos-office's parse_xlsx returns TabularDocument (different type
    # from ContentDocument), wiring deferred to a follow-up.
    supported_upload_extensions: tuple[str, ...] = (".pdf", ".docx", ".pptx")

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=(".env", "../.env"),
        extra="ignore",
        validate_default=True,
    )

    @model_validator(mode="after")
    def _validate_security_invariants(self) -> AppSettings:
        if self.env == "test":
            return self

        if self.env == "production" and self.log_level.upper() == "DEBUG":
            raise SettingsError(
                "APP_LOG_LEVEL=DEBUG is not allowed when APP_ENV=production.\n"
                "How to fix: set APP_LOG_LEVEL=INFO or higher in .env.\n"
                "Alternative: set APP_ENV=development for local dev."
            )

        if not self.default_model or ":" not in self.default_model:
            raise SettingsError(
                f"APP_DEFAULT_MODEL must be in 'provider:model' format, got "
                f"{self.default_model!r}.\n"
                "How to fix: set e.g. APP_DEFAULT_MODEL=anthropic:claude-haiku-4-5.\n"
                "Alternative: see backend/app/services/catalog.py for the supported list."
            )

        return self
