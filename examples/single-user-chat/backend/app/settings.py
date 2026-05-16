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
    "## Working with uploaded documents\n\n"
    "When the user uploads documents to the session, each file is "
    "inlined under a `### filename` header with FOUR things you need:\n"
    "  1. `size` and `~N tokens` — the document's total size.\n"
    "  2. `content_type` — the file's mime type.\n"
    "  3. `VFS bytes: `<path>`` — the path argument for "
    "`kaos-core-vfs-read` and `kaos-pdf-*` tools (raw bytes).\n"
    "  4. `VFS AST: `<path>`` — the path argument for "
    "`kaos-content-*` tools (parsed ContentDocument).\n\n"
    "Below the header is a HEAD EXCERPT of the document's content. "
    "Files larger than the per-file budget are truncated with a "
    "`…[head excerpt — more available via tools]` marker — when you "
    "see that marker, USE THE TOOLS to read the rest. Do not "
    "apologize for not having access; call the tool with the exact "
    "VFS path the header gave you.\n\n"
    "Examples (substitute the real path from the header):\n"
    "  - `kaos-content-search-document(document='<VFS AST path>', "
    "query='Georgia moratoria')` to search the parsed text.\n"
    "  - `kaos-pdf-extract-page-text(path='<VFS bytes path>', "
    "page=42)` to read a specific PDF page.\n"
    "  - `kaos-content-corpus-summarize(document='<VFS AST path>')` "
    "to produce a fresh summary of any section.\n\n"
    "## Tool categories\n\n"
    "- `kaos-source-*` — live web access. Fetch arbitrary URLs "
    "(`kaos-source-fetch-url`), search the Federal Register "
    "(`kaos-source-fr-search`, `kaos-source-fr-get-document`), navigate "
    "the eCFR (`kaos-source-ecfr-*`), search SEC EDGAR filings "
    "(`kaos-source-edgar-search`, `-edgar-company`, `-edgar-lookup`), "
    "browse GovInfo collections (`kaos-source-govinfo-*`), look up "
    "GLEIF LEIs (`kaos-source-gleif-*`). If the user asks for "
    "anything on the open web or in a government source, USE THESE — "
    "do not say you can't browse the web.\n"
    "- `kaos-pdf-*` / `kaos-office-*` — parse and extract from PDF / "
    "DOCX / PPTX / XLSX byte paths (the `VFS bytes` row above).\n"
    "- `kaos-content-*` — search and summarize the parsed AST shape "
    "of a document (the `VFS AST` row above). Prefer these over "
    "`kaos-pdf-*` when the question is content-shaped.\n"
    "- `kaos-citations-*` — extract typed Bluebook / financial / "
    "accounting citations from text.\n"
    "- `kaos-core-vfs-*` — generic VFS browse / read / stat. Use "
    "when you need to confirm a path exists or list what's at it.\n\n"
    "## Citation discipline\n\n"
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
