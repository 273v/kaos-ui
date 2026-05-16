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

# Default per-session system prompt. Identity + voice only — kept
# short on purpose. Tool catalog is injected by
# `kaos_ui.agents.augment_instructions`; the date preamble is
# injected at the same layer; behavior policy (when to call which
# tool, search-before-clarify, search-before-answer) lives in the
# kaos-agents planner + critic Signature docstrings, not here.
# See kaos-modules/docs/plans/thin-worker-prompt.md for the full
# rationale and the anti-goals list that blocks regrowing this string.
_DEFAULT_SYSTEM_PROMPT = (
    "You are Kelvin, a meticulous legal-research assistant. Use the "
    "tools available in this session to answer the user's question; "
    "cite the source filename or URL for any fact you report. Be "
    "actively helpful — when the user uploads documents, propose what "
    "you could do with them. Communicate directly using 'I' and "
    "'you'; format with Markdown. Do not refer to yourself as an AI, "
    "chatbot, or large language model."
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
    # AgenticLoop tuning. The loop's per-iteration planner +
    # GoalChecker each run an LLM call; Haiku is the right default
    # because both are tight-prompt classifiers running BEFORE each
    # iteration (latency + cost matter). Override to Sonnet for
    # harder routing (catalog growing beyond ~10 groups) or to a
    # smaller / local model for high-throughput deploys. Set None
    # to use the kaos-agents defaults baked into the Signatures.
    agentic_planner_model: str | None = "anthropic:claude-haiku-4-5"
    agentic_goal_check_model: str | None = "anthropic:claude-haiku-4-5"
    # Soft char-cap on the input the summarizer sends to the LLM.
    # This bounds ONLY the at-upload-time `summary` field — a 2-3
    # sentence "what kind of document is this?" snippet. It is NOT
    # the chat-context cap (see `_PER_FILE_PROMPT_BUDGET` in
    # services/uploads.py for that). A 10k-char head covers the
    # caption / parties / definitions / recitals of a typical legal
    # document, which is enough to identify type + key entities.
    # Users who want a deeper "summarize this whole document"
    # treatment should call `kaos-content-corpus-summarize` from
    # the chat interface instead.
    summary_input_cap_chars: int = 10_000

    # Per-file budget for the CHAT-CONTEXT corpus inlined into the
    # agent's system prompt on every turn (distinct from
    # `summary_input_cap_chars` above, which sizes the at-upload-time
    # summary). 40k chars ≈ 10k tokens per file — fits ≤20 files in
    # Haiku 4.5's 200k context after headroom for the instruction
    # template + chat history + response. For Sonnet 4.6's 1M context
    # window, raising this 5x is safe. Files larger than the budget
    # get a truncation note + a hint pointing the agent at the
    # search tools and the file's VFS path so it can dig deeper
    # tool-side rather than guessing about content past the head.
    per_file_prompt_budget_chars: int = 40_000

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
