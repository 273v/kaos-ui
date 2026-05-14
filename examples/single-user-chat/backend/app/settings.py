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
    "You are a helpful research assistant with real tool access. Use the "
    "tools liberally instead of guessing or apologizing for not having "
    "capabilities.\n\n"
    "Tool categories available to you when tools are enabled:\n"
    "- `kaos-source-*` — live web access. Fetch arbitrary URLs "
    "(kaos-source-fetch-url), search the Federal Register "
    "(kaos-source-fr-search, kaos-source-fr-get-document), navigate the "
    "eCFR (kaos-source-ecfr-*), search SEC EDGAR filings "
    "(kaos-source-edgar-search, -edgar-company, -edgar-lookup), browse "
    "GovInfo collections (kaos-source-govinfo-*), look up GLEIF LEIs "
    "(kaos-source-gleif-*). If the user asks for anything on the open "
    "web or in a government source, USE THESE — do not say you can't "
    "browse the web.\n"
    "- `kaos-pdf-*` / `kaos-office-*` / `kaos-content-*` — parse, "
    "extract from, and search uploaded documents (PDF, DOCX, PPTX, "
    "XLSX). Use these whenever the user references an attached file.\n"
    "- `kaos-citations-*` — extract typed Bluebook / financial / "
    "accounting citations from text.\n"
    "- `kaos-core-vfs-*` — read files the user has uploaded into the "
    "session's virtual filesystem.\n\n"
    "When you cite a document, name it explicitly. When you cite an "
    "external source, include the URL or canonical reference (e.g., "
    "the FR document number, the eCFR section, the SEC accession)."
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

    # Model used by the auto-titler + document summarizer Programs.
    # Haiku is the default — cheapest current-gen Anthropic, fast
    # enough for the every-10-turn cadence. Override to Sonnet for
    # richer titles on dense conversations, or to a local model.
    auto_title_model: str = "anthropic:claude-haiku-4-5"
    summarizer_model: str = "anthropic:claude-haiku-4-5"
    # Soft char-cap on the input the summarizer sends to the LLM.
    # 800k chars ≈ 200k tokens — comfortable inside Haiku 4.5 +
    # Sonnet 4.6's context windows with headroom for the instruction
    # template. This is a RUNAWAY-COST GUARD, not a quality knob: a
    # full SEC filing or deal-room PDF must NOT be silently truncated
    # to a head-excerpt (the prior 12k-char cap was wrong for legal
    # use). Raise the cap (or switch to Sonnet, whose context is 1M)
    # if your documents routinely exceed this. Track logged-truncation
    # events to know when you've crossed the line.
    summary_input_cap_chars: int = 800_000

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
