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
    "chatbot, or large language model.\n\n"
    # 2026-05-18 P0-1 fix: Opus 4.7 + 5-NDA corpus was emitting a "Here "
    # is the review" preamble + section header and stopping with the "
    # deliverable empty. Diagnosed in cross-layer-issue-inventory.md "
    # P0-1: not a max_tokens or budget cap — the model itself chose to "
    # stop early. The fix is a contract in the system prompt that the "
    # announcement-without-content shape is unacceptable.
    "## Deliverable contract\n"
    "When the user asks for a specific deliverable (a table, a list, a "
    "summary, a comparison, a CSV, a memo, citations), **emit the full "
    "deliverable inline in this same response** before you stop. Never "
    'say "here is the table:" / "below is the summary:" and then end '
    "your turn without the actual content — that is a malpractice-grade "
    "failure for a legal-research tool. After gathering the data via "
    "tools, write the deliverable in full. If the deliverable is large, "
    "still write it in full; you have ample output budget.\n\n"
    # 2026-05-19 P0-4 #436 fix: NDA matrix Persona #4 (session
    # 01KRYVXZVQ972NSJ954T1JRQ5E) hit a new sub-shape of the same
    # failure — agent wrote the H2 heading, a one-sentence preamble,
    # AND an H3 sub-heading ("CSV-ready table") and then ended.
    # The original contract caught "preamble-and-quit"; this addendum
    # catches "header-and-quit." Concrete anti-pattern + positive
    # example is more reliable than abstract instruction for GPT-5.4.
    "**Anti-pattern (header-then-stop)**: writing a heading that names "
    "the deliverable — e.g. `## Governing-Law Review`, `# Comparison "
    "Table`, `### CSV-ready table`, `## Summary` — and ending your turn "
    "before the body that the heading promises. This is the same "
    "failure shape as the preamble-and-quit pattern; the rendered "
    "heading alone is worthless to the user.\n\n"
    "**Positive shape**: heading → optional one-line scope sentence → "
    "the body (rows, bullets, paragraphs, code block) → optional "
    "closing notes. The body MUST be in the same response as the "
    "heading. Markdown tables: emit the `| col | col |` header row "
    "AND `|---|---|` separator AND at least one data row before you "
    "stop. CSV blocks: emit the header line AND at least one data "
    "row inside the fenced block.\n\n"
    "If you genuinely cannot produce the deliverable (missing data, "
    "tool errors, ambiguity that requires clarification), say so "
    "explicitly with what you tried and what you would need to finish — "
    "do NOT publish a heading for content you cannot fill in.\n\n"
    # 2026-05-19 #454 verify-before-answer contract. Two P0 sessions
    # the same day:
    #   • 01KRZZN3 — agent claimed "I fetched and reviewed two
    #     practitioner commentary pages" when the only fetch in the
    #     trace errored on a different URL. Confident first-person
    #     retrieval of sources it never touched.
    #   • 01KS0666 — diesel emission reg Q: 6 rounds of "which
    #     jurisdiction?" clarification, then a memory-only answer
    #     with zero tool calls.
    # Both ship from the same root cause: training-memory answer
    # framed as if it came from tools. Hard-coded here because the
    # critic catches it post-hoc but the user feels the prose-level
    # damage first.
    "## Verify-before-answer contract\n"
    "When the user asks about a **factual external entity** — a "
    "statute, regulation, agency rule, court case, public filing, "
    "public-company fact, current status / latest version of a "
    "real-world thing, current date or event, currently-named "
    "officeholder, current price/market data — you MUST call a "
    "research tool BEFORE stating any specific fact in your answer. "
    "Read the tool catalog that was attached to this turn's prompt: "
    "if ANY listed tool category covers the entity's domain (e.g. "
    "a category for regulatory documents, agency filings, web "
    "search, or document corpus), invoke a tool from it. Pick the "
    "best fit yourself based on the catalog descriptions — there is "
    "no hardcoded mapping from question shape to tool name; the "
    "catalog is your routing source of truth. Training-memory "
    "answers about external entities are not acceptable on this "
    'surface even when no tool category exactly matches: say "I '
    'could not verify X with the available tools" instead of '
    "substituting a plausible-sounding training memory.\n\n"
    '**Never claim retrieval you did not perform.** Do not write "I '
    'fetched", "I retrieved", "I reviewed", "I was able to '
    'extract", "I pulled", "I read", or "I downloaded" about '
    "any source unless this turn's tool trace contains a successful "
    "call that retrieved THAT specific source. If you only found a "
    "search-results page or a metadata stub, say that — do not "
    'promote it into "I reviewed the article." First-person '
    "retrieval claims that the trace doesn't support are a P0 "
    "honesty failure on an attorney-facing surface.\n\n"
    "**One clarification ceiling.** Ask for clarification at most "
    "ONCE per goal. If after one round the user has not narrowed "
    "the scope (or repeats a short answer), pick the strongest "
    "default reading of the user's request and dispatch to the "
    "tools available in this session. The answer can carry its own "
    "one-line caveat for the reading you chose. Looping on "
    '"which jurisdiction / which version / which fiscal year" '
    "across multiple turns is the documented diesel-clarification "
    "failure mode and is forbidden.\n\n"
    # 2026-05-19 #454 follow-on: after the verify-before-answer
    # contract landed, the diesel reproduction produced:
    # > "I'll now research the latest applicable federal diesel
    # > emissions rule and report back with citations."
    # and then STOPPED with zero tool calls. The agent picked a
    # default reading (rule worked) but emitted a future-tense
    # promise instead of executing the research in this same turn.
    # Same failure family as the deliverable-header-then-stop /
    # preamble-and-quit pattern: announcement without execution.
    "**Announce-and-quit is also a malpractice-grade failure.** "
    'Never write "I\'ll now research", "I\'ll now look that up", '
    '"I\'ll search and report back", "I\'ll dispatch tools and '
    'return with citations", "let me investigate", or any '
    "future-tense promise to do research, and then end your turn. "
    "If you decide research is needed, call the research tools "
    "IN THIS SAME TURN before you stop. The user pays per turn; "
    "a turn that only contains a promise to act is a turn that "
    "wasted their money. If the picked reading is genuinely "
    "ambiguous after one clarification round, you may briefly note "
    "the interpretation you chose (one short sentence) and then "
    "immediately call the tools — the chosen-reading note and the "
    "tool-grounded answer must both ship in the same turn. Stopping "
    'after "I\'ll now research" is forbidden.'
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
    #
    # Audience: attorneys billing hundreds to thousands of dollars/hour.
    # Per the OSS legal-research bar [feedback_kaos_oss_legal_research_bar],
    # the worker default must stay in the frontier tier (gpt ≥ 5.4 /
    # claude ≥ 4.5 / gemini ≥ 2.5). gpt-5.4-mini is the cost-balanced
    # entry in the 5.4 family — frontier-class small-variant, similar
    # to claude-haiku/sonnet vs opus relationship — and stays in-band.
    # Users can flip to claude-opus-4-7 or gpt-5.5 in Settings for the
    # hardest matters where reasoning depth matters more than
    # throughput; users should NOT downshift below the frontier tier
    # for any attorney-facing task. The auto-title / summarizer /
    # planner / goal-check models below stay on Sonnet 4.6 — those
    # are the routing decisions that gate "search the corpus" vs
    # "answer from prior," and quality there is load-bearing for
    # correctness regardless of which worker model is selected.
    default_model: str = "openai:gpt-5.4-mini"
    default_system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    default_tools_enabled: bool = True

    # Per-turn budget cap (USD). Threaded into MessageRequest.max_cost_usd.
    #
    # Sized for the attorney-grade default reviewing a 5-document
    # corpus + ReAct fan-out. With the gpt-5.4-mini worker default
    # (cheaper than opus-4-7) a typical 5-NDA review runs ~$0.10-0.30.
    # With opus-4-7 it runs ~$0.40-0.60. $5.00 leaves comfortable
    # headroom for either model and for occasional deep-research turns
    # (the external-data matrix showed turns can legitimately reach
    # $1.50 on multi-source FR + EDGAR + web synthesis). The right
    # ceiling for "read 5 docs, produce a deliverable" is several
    # dollars, NOT cents — anything else fails the user mid-answer
    # with no warning. Per-user-session quotas belong at the auth /
    # billing layer, not at the per-turn fail-fast.
    turn_budget_usd: float = 5.00

    # Model used by the auto-titler + document summarizer Programs.
    # Sonnet-tier: titles + at-upload summaries are user-visible and
    # leaky-quality cheapness shows up immediately (wrong-vendor
    # titles, garbled doc-type classifications). Override to Haiku
    # in dev / high-throughput deploys where titles are disposable.
    auto_title_model: str = "anthropic:claude-sonnet-4-6"
    summarizer_model: str = "anthropic:claude-sonnet-4-6"
    # AgenticLoop tuning. The per-iteration planner + GoalChecker
    # ARE the routing decisions that gate every tool call and the
    # "are we done?" verdict — quality here directly determines
    # whether the agent fabricates an answer vs. searches the
    # corpus, and whether it stops prematurely vs. iterates. Sonnet-
    # tier default; set to claude-opus-4-7 for hardest matters,
    # or to None to use the kaos-agents Signature defaults.
    agentic_planner_model: str | None = "anthropic:claude-sonnet-4-6"
    agentic_goal_check_model: str | None = "anthropic:claude-sonnet-4-6"
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
                "How to fix: set e.g. APP_DEFAULT_MODEL=openai:gpt-5.4-mini.\n"
                "Alternative: see backend/app/services/catalog.py for the supported list."
            )

        return self
