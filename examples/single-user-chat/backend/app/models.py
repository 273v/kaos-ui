"""Pydantic API contracts for the Single-User Chat extension routes.

These are the shapes our `/v1/models` and `/v1/chat/*` endpoints accept
and return. The kaos-agents-owned `/v1/sessions/*` routes have their own
shapes (SessionCreateRequest, MessageRequest, etc.) defined in
kaos_agents.api.server — we don't redeclare those.

See docs/ARCHITECTURE.md § 3.3 for the design.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, Field, computed_field, model_validator

if TYPE_CHECKING:
    from kaos_agents.types import SessionPolicy as _SessionPolicy

Provider = Literal["anthropic", "openai", "google", "xai"]


# ── tool policy (TR-3) ────────────────────────────────────────────────


Persona = Literal["research", "drafting", "forensics"]

# Recursion guard — these 4 tools let kaos-agents call itself, which
# the AgenticLoop's auto-elevation could otherwise drag into the
# allowed set (the `agents` group is yellow-confirm but accidental
# elevation would still be bad). Pinned at persistence time so a
# disabled-then-re-enabled session can never lose the floor.
SELF_RECURSIVE_AGENT_TOOLS: frozenset[str] = frozenset(
    {
        "kaos-agent-chat",
        "kaos-agent-plan",
        "kaos-agent-findings",
        "kaos-agent-corpus-filter",
    }
)


def with_denied_floor(denied_tools: list[str]) -> list[str]:
    """Return ``denied_tools`` with the self-recursive guard set merged in.

    Idempotent + order-preserving for whatever the caller passed in;
    the floor entries are appended (sorted) only when absent.
    """
    existing = set(denied_tools)
    additions = sorted(SELF_RECURSIVE_AGENT_TOOLS - existing)
    if not additions:
        return list(denied_tools)
    return list(denied_tools) + additions


class SessionToolSetWire(BaseModel):
    """LEGACY — kept for back-compat with sessions persisted under the
    pre-AgenticLoop shape (TR-3 / kaos-agents 0.1.0a2).

    New code should use :class:`SessionPolicyWire`, which carries the
    same ceiling + denied_tools + auto_narrow PLUS the AgenticLoop's
    two-tier ceiling (soft_ceiling) + elevation policy + loop budget.
    The migration validator on :class:`SessionMeta` rewrites old
    `tool_set` payloads into the new `policy` shape on load — no live
    callers should hit this class directly.
    """

    allowed_groups: list[str] = Field(
        default_factory=lambda: ["documents", "citations", "vfs"],
        description=(
            "Tool group names that are allowed for this session "
            "(ceiling). Defaults to documents+citations+vfs — web is "
            "opt-in because of cost and privacy implications."
        ),
    )
    denied_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Tool names that are always blocked, even if their group is "
            "allowed. The hard read-only floor lives here at config "
            "time so user toggles can never accept a write tool."
        ),
    )
    auto_narrow: bool = Field(
        default=True,
        description=(
            "When True, the TurnToolPolicy planner Program runs before "
            "each turn and may narrow the effective tool set within "
            "this ceiling. When False, the full ceiling is used."
        ),
    )

    @property
    def is_blocking_all(self) -> bool:
        """True when the ceiling allows no tools (allowed_groups=[])."""
        return not self.allowed_groups


class SessionPolicyWire(BaseModel):
    """Per-session two-tier policy — wire shape for SessionMeta.

    Successor to :class:`SessionToolSetWire`. Round-trips through
    :class:`kaos_agents.types.SessionPolicy` via
    :meth:`to_session_policy`. Carries:

    - **`allowed_groups`** — current working set of tool groups (the
      ceiling).
    - **`soft_ceiling`** — maximum the AgenticLoop may auto-elevate
      `allowed_groups` to. Set at session creation by the persona
      chip + immutable for the session.
    - **`denied_tools`** — explicit deny list. Wins over every allow.
    - **`persona`** — the named preset for this session
      (`"research"` / `"drafting"` / `"forensics"`). Threaded into
      the per-turn TurnToolPolicy Signature as `session_intent`.
    - **`auto_narrow`** + **`auto_elevate`** + **`auto_loop`** —
      three independent toggles for the AgenticLoop behaviors.
    - **`max_loop_iterations`** + **`max_loop_cost_usd`** +
      **`max_loop_wall_clock_seconds`** — three independent loop
      limiters (per Pydantic AI usage_limits best practice).
    """

    allowed_groups: list[str] = Field(
        default_factory=lambda: sorted(
            [
                "web",
                "browser",
                "netinfra",
                "documents",
                "citations",
                "vfs",
                "forensics",
                "retrieval",
            ]
        ),
        description=(
            "Tool group names currently allowed. The AgenticLoop may "
            "auto-elevate this toward `soft_ceiling` mid-turn when the "
            "per-turn planner reports `dropped_groups`. Mirrors the "
            "research persona's initial allowed_groups (== soft_ceiling)."
        ),
    )
    soft_ceiling: list[str] = Field(
        default_factory=lambda: sorted(
            [
                "web",
                "browser",
                "netinfra",
                "documents",
                "citations",
                "vfs",
                "forensics",
                "retrieval",
            ]
        ),
        description=(
            "Maximum the AgenticLoop may elevate `allowed_groups` to "
            "without explicit user consent. Set by persona at session "
            "creation; user can override via SettingsSheet."
        ),
    )
    denied_tools: list[str] = Field(
        default_factory=lambda: sorted(
            [
                "kaos-agent-chat",
                "kaos-agent-plan",
                "kaos-agent-findings",
                "kaos-agent-corpus-filter",
            ]
        ),
        description=(
            "Tool names always blocked. Inherits the 4 self-recursive "
            "kaos-agents tools by default so accidental opt-in to the "
            "`agents` group doesn't trigger infinite recursion."
        ),
    )
    persona: Persona = Field(
        default="research",
        description=(
            "Named preset (research / drafting / forensics). Drives "
            "the soft_ceiling default + threaded into the per-turn "
            "planner's `session_intent` Signature input."
        ),
    )
    auto_narrow: bool = Field(
        default=True,
        description=(
            "Per-turn TurnToolPolicy planner toggle. When True, the "
            "AgenticLoop narrows the ceiling to just the groups this "
            "message needs."
        ),
    )
    auto_elevate: bool = Field(
        default=True,
        description=(
            "Master toggle for auto-elevation. When True, the "
            "AgenticLoop consults elevation_policy to decide whether "
            "to silently elevate (green-auto), pause for approval "
            "(yellow-confirm), or refuse (red-blocked) when the "
            "planner wants groups outside `allowed_groups`."
        ),
    )
    auto_loop: bool = Field(
        default=True,
        description=(
            "Multi-iteration loop toggle. When True, the AgenticLoop "
            "runs plan → execute → goal-check → replan up to "
            "max_loop_iterations. When False, the loop runs exactly "
            "one ReAct iteration (pre-loop behavior)."
        ),
    )
    max_loop_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Hard cap on iterations per turn. Default 3 covers the "
            "vast majority of replan scenarios; tighten for cost "
            "savings, loosen for deep-research workflows."
        ),
    )
    max_loop_cost_usd: float = Field(
        default=0.25,
        gt=0.0,
        le=10.0,
        description=(
            "Hard cap on cumulative LLM cost per turn (planner + "
            "critic + worker). Default $0.25; increase for "
            "Sonnet-class drafting workflows."
        ),
    )
    max_loop_wall_clock_seconds: float = Field(
        default=60.0,
        gt=0.0,
        le=600.0,
        description=(
            "Hard cap on wall-clock time per turn. Defense in depth "
            "against a hung provider call the cost cap wouldn't catch."
        ),
    )

    @property
    def is_blocking_all(self) -> bool:
        """True when the ceiling allows no tools."""
        return not self.allowed_groups

    def to_session_policy(self) -> _SessionPolicy:
        """Round-trip into the kaos-agents value type for AgenticLoop consumption."""
        # Local import: kaos-agents is heavy; only load when actually building a policy.
        from kaos_agents.types import SessionPolicy

        return SessionPolicy(
            allowed_groups=frozenset(self.allowed_groups),
            soft_ceiling=frozenset(self.soft_ceiling),
            denied_tools=frozenset(self.denied_tools),
            auto_narrow=self.auto_narrow,
            auto_elevate=self.auto_elevate,
            auto_loop=self.auto_loop,
            max_loop_iterations=self.max_loop_iterations,
            max_loop_cost_usd=self.max_loop_cost_usd,
            max_loop_wall_clock_seconds=self.max_loop_wall_clock_seconds,
        )

    @classmethod
    def from_session_policy(cls, policy: _SessionPolicy) -> SessionPolicyWire:
        """Inverse of :meth:`to_session_policy`."""
        return cls(
            allowed_groups=sorted(policy.allowed_groups),
            soft_ceiling=sorted(policy.soft_ceiling),
            denied_tools=sorted(policy.denied_tools),
            auto_narrow=policy.auto_narrow,
            auto_elevate=policy.auto_elevate,
            auto_loop=policy.auto_loop,
            max_loop_iterations=policy.max_loop_iterations,
            max_loop_cost_usd=policy.max_loop_cost_usd,
            max_loop_wall_clock_seconds=policy.max_loop_wall_clock_seconds,
        )

    @classmethod
    def for_persona(cls, persona: Persona) -> SessionPolicyWire:
        """Build a policy for a named persona preset.

        Delegates to :meth:`kaos_agents.types.SessionPolicy.for_persona`
        so the soft_ceiling defaults stay in sync with the kaos-agents
        canonical definition.
        """
        from kaos_agents.types import SessionPolicy

        policy = SessionPolicy.for_persona(persona)
        wire = cls.from_session_policy(policy)
        return wire.model_copy(update={"persona": persona})


# ── AgenticLoop SSE event payloads ────────────────────────────────────


class ToolPolicyElevatedWire(BaseModel):
    """SSE wire shape for :class:`kaos_agents.events.ToolPolicyElevated`."""

    type: Literal["tool_policy_elevated"] = "tool_policy_elevated"
    elevated_groups: list[str]
    kept_groups: list[str]
    previous_allowed: list[str]
    rationale: str
    iteration: int


class CapabilityRequestedWire(BaseModel):
    """SSE wire shape for :class:`kaos_agents.events.CapabilityRequested`."""

    type: Literal["capability_requested"] = "capability_requested"
    requested_groups: list[str]
    justification: str
    iteration: int
    previous_allowed: list[str]


class GoalCheckedWire(BaseModel):
    """SSE wire shape for :class:`kaos_agents.events.GoalChecked`."""

    type: Literal["goal_checked"] = "goal_checked"
    kind: Literal["satisfied", "needs_more_work", "insufficient_evidence"]
    rationale: str
    next_action: str = ""
    missing: str = ""
    confidence: float = 0.0
    iteration: int
    cost_usd: float
    latency_ms: float


class LoopTerminatedWire(BaseModel):
    """SSE wire shape for :class:`kaos_agents.events.LoopTerminated`."""

    type: Literal["loop_terminated"] = "loop_terminated"
    reason: Literal[
        "satisfied",
        "insufficient_evidence",
        "max_iterations",
        "cost_exceeded",
        "wall_clock_exceeded",
        "stuck_no_progress",
        "user_interrupt",
    ]
    iterations_used: int
    elevations_used: int
    cost_usd: float
    wall_clock_ms: float


class ModelEntry(BaseModel):
    """One row of the model picker catalog."""

    id: str = Field(description="provider:model string, e.g. 'anthropic:claude-haiku-4-5'")
    label: str = Field(description="Human-readable name shown in the UI")
    provider: Provider
    recommended_for: str | None = None
    context_window: int | None = None


class ModelListResponse(BaseModel):
    models: list[ModelEntry]


class SessionMeta(BaseModel):
    """Our metadata sidecar for a kaos-agents session.

    Stored at `.kaos-vfs/single-user-chat/sessions/{id}/meta.json`.

    Tool-policy field history (three-state migration):
      1. Pre-TR-3: legacy bool `tools_enabled` only.
      2. TR-3 / kaos-agents 0.1.0a2: `tool_set: SessionToolSetWire`.
      3. AgenticLoop / kaos-agents 0.1.0a4 (current):
         `policy: SessionPolicyWire`.

    The `_migrate_tool_policy` validator hydrates from any of the
    three shapes; `tool_set` survives as a computed_field for SPA
    back-compat until the frontend cuts over.
    """

    id: str = Field(description="ULID, shared with the kaos-agents session_id")
    title: str
    model: str
    system_prompt: str
    # AgenticLoop source of truth — see SessionPolicyWire for the full
    # shape. The previous `tool_set: SessionToolSetWire` is preserved
    # as a computed_field below so SPA clients on the old schema keep
    # working through the cutover window.
    policy: SessionPolicyWire = Field(default_factory=SessionPolicyWire)
    created_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0
    archived: bool = False
    # User favorite — sidebar lifts these to the top when sorted.
    starred: bool = False
    # "auto" titles get re-summarized as the conversation grows;
    # "manual" titles (user renamed via the settings sheet or the
    # inline pencil) stick until the user changes them again.
    title_source: Literal["manual", "auto"] = "auto"
    # Wall-clock of the last auto-title generation. Used to throttle
    # re-summarization (default cadence: every 10 messages OR 24h).
    title_updated_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tool_set(self) -> SessionToolSetWire:
        """Back-compat view: derive the old SessionToolSetWire shape.

        SPA clients on the pre-AgenticLoop schema read this field. The
        derived shape preserves the old (allowed_groups + denied_tools
        + auto_narrow) triple from the new policy. Will be dropped one
        release after the SPA cuts over to reading `policy` directly.
        """
        return SessionToolSetWire(
            allowed_groups=self.policy.allowed_groups,
            denied_tools=self.policy.denied_tools,
            auto_narrow=self.policy.auto_narrow,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tools_enabled(self) -> bool:
        """Backward-compat derived view: True when ANY group is allowed."""
        return not self.policy.is_blocking_all

    @model_validator(mode="before")
    @classmethod
    def _migrate_tool_policy(cls, data: object) -> object:
        """Hydrate `policy` from any of the three historic shapes.

        - **State 3 (current)**: `policy: SessionPolicyWire` present →
          drop any stale `tool_set` / `tools_enabled` keys so the
          computed_fields are authoritative.
        - **State 2 (TR-3 / 0.1.0a2)**: `tool_set: SessionToolSetWire`
          → upgrade to `policy` with the soft_ceiling defaulted to
          the research persona (preserves user's narrowed
          `allowed_groups` + carries the new loop knobs).
        - **State 1 (pre-TR-3)**: only `tools_enabled: bool` → if
          False, block everything; if True (or absent), default
          research persona.

        Live data is never double-mapped: we mutate `data` in place
        and remove the stale keys.
        """
        if not isinstance(data, dict):
            return data
        # ty narrows `dict` from `object` to `dict[Unknown, Unknown]`
        # and then refuses heterogeneous str→Any assignments because
        # `dict` is invariant in its type parameters. Re-bind through
        # an explicit cast so the rest of the function works against
        # `dict[str, object]`.
        d = cast("dict[str, object]", data)

        # State 3 — already on the new shape.
        if "policy" in d:
            d.pop("tool_set", None)
            d.pop("tools_enabled", None)
            return d

        # State 2 — upgrade SessionToolSetWire → SessionPolicyWire.
        if d.get("tool_set"):
            raw_old = d.pop("tool_set")
            old = cast("dict[str, object]", raw_old) if isinstance(raw_old, dict) else {}
            raw_allowed = old.get("allowed_groups", [])
            allowed = list(raw_allowed) if isinstance(raw_allowed, list) else []
            raw_denied = old.get("denied_tools", [])
            denied = list(raw_denied) if isinstance(raw_denied, list) else []
            auto_narrow = bool(old.get("auto_narrow", True))
            # Default to research persona soft_ceiling on upgrade
            # (matches the v2 plan: research is the 80% default).
            from kaos_agents.types.session_policy import RESEARCH_SOFT_CEILING

            d["policy"] = {
                "allowed_groups": allowed,
                "soft_ceiling": sorted(RESEARCH_SOFT_CEILING),
                "denied_tools": denied,
                "persona": "research",
                "auto_narrow": auto_narrow,
                "auto_elevate": True,
                "auto_loop": True,
                "max_loop_iterations": 3,
                "max_loop_cost_usd": 0.25,
                "max_loop_wall_clock_seconds": 60.0,
            }
            d.pop("tools_enabled", None)
            return d

        # State 1 — legacy bool. False = block-all, True/missing = default.
        legacy = d.pop("tools_enabled", None)
        if legacy is False:
            d["policy"] = {
                "allowed_groups": [],
                "soft_ceiling": [],
                "denied_tools": [],
                "persona": "research",
                "auto_narrow": True,
                "auto_elevate": True,
                "auto_loop": True,
            }
        # legacy True or None → default research persona (field default).
        return d


class SessionSummary(BaseModel):
    """Lightweight row used in the sidebar list."""

    id: str
    title: str
    model: str
    last_message_at: datetime | None
    created_at: datetime
    message_count: int
    archived: bool = False
    starred: bool = False
    title_source: Literal["manual", "auto"] = "auto"


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    next_cursor: str | None = None


# Bounded inputs. Bounds match the kaos-llm-client context-window floor
# (~32k tokens ≈ 100k chars), with headroom for the model + message and
# a single fixed turn budget.
_MAX_TITLE_LEN = 120
_MAX_PROMPT_LEN = 8000
_MAX_MESSAGE_LEN = 16000
_MAX_MODEL_LEN = 80  # 'provider:model-name-with-dashes-x.y' fits well below


class CreateSessionBody(BaseModel):
    title: str | None = Field(default=None, max_length=_MAX_TITLE_LEN)
    model: str | None = Field(default=None, max_length=_MAX_MODEL_LEN)
    system_prompt: str | None = Field(default=None, max_length=_MAX_PROMPT_LEN)
    tools_enabled: bool | None = None


class PatchMetaBody(BaseModel):
    title: str | None = Field(default=None, max_length=_MAX_TITLE_LEN)
    model: str | None = Field(default=None, max_length=_MAX_MODEL_LEN)
    system_prompt: str | None = Field(default=None, max_length=_MAX_PROMPT_LEN)
    tools_enabled: bool | None = None
    starred: bool | None = None


# ── tool-policy routes (TR-4) ─────────────────────────────────────────


class CategoryInfo(BaseModel):
    """One row of GET /v1/chat/categories.

    Sourced from kaos-agents' ``default_tool_group_registry`` joined
    with kaos-ui's :data:`KAOS_TOOL_GROUP_DESCRIPTIONS`. The SPA
    renders one checkbox per row in the SettingsSheet (TR-8).
    """

    id: str = Field(description="Group name, eg. 'documents'.")
    label: str = Field(description="Human-readable label for the checkbox.")
    description: str = Field(description="Tooltip / hint for the user.")
    default_enabled: bool = Field(
        description=(
            "Whether new sessions include this group in their ceiling. "
            "Maps to :class:`SessionToolSetWire`'s default_factory."
        ),
    )
    tool_count: int = Field(description="Number of tools currently in this group.")


class CategoriesResponse(BaseModel):
    """GET /v1/chat/categories response."""

    categories: list[CategoryInfo]


class ToolSetUpdateBody(BaseModel):
    """PATCH /v1/chat/sessions/{id}/tool-set body.

    Every field optional — pass only the dimension you're changing.
    ``allowed_groups`` empty list means "block all" (the session is
    fully read-only at the proxy layer).

    M.6: the body widened from the legacy ``allowed_groups`` /
    ``denied_tools`` / ``auto_narrow`` trio to also carry the three
    AgenticLoop toggles (``auto_elevate`` / ``auto_loop`` /
    ``persona``). Pre-M.6 the SPA's PlanActChip and SettingsSheet
    had no way to flip those bits — the chip silently piggy-backed
    on ``auto_narrow`` which left ``auto_loop``/``auto_elevate``
    untouched and the chip's "Plan" mode wedged.
    """

    allowed_groups: list[str] | None = Field(
        default=None,
        description="New ceiling. Use [] to block everything.",
    )
    denied_tools: list[str] | None = Field(
        default=None,
        description="New per-session deny list. Override the policy floor.",
    )
    auto_narrow: bool | None = Field(
        default=None,
        description=(
            "When true, the TurnToolPolicy planner runs per-turn within "
            "the ceiling. When false, the full ceiling is used every turn."
        ),
    )
    auto_elevate: bool | None = Field(
        default=None,
        description=(
            "When true, the AgenticLoop may silently widen "
            "``allowed_groups`` up to ``soft_ceiling`` whenever the "
            "per-turn planner reports green-auto ``dropped_groups``. "
            "When false, the loop runs with only the current "
            "``allowed_groups`` (no auto-elevation)."
        ),
    )
    auto_loop: bool | None = Field(
        default=None,
        description=(
            "When true, enable the multi-iteration AgenticLoop with "
            "goal checking between iterations. When false, the chat "
            "router runs a single ReAct turn (pre-loop behavior)."
        ),
    )
    persona: Persona | None = Field(
        default=None,
        description=(
            "Named persona preset for this session — threaded into "
            "the per-turn TurnToolPolicy Signature as session_intent. "
            "Does NOT rewrite ``allowed_groups`` / ``soft_ceiling`` "
            "(those are explicit fields the caller must pass alongside "
            "if they want a full persona swap)."
        ),
    )


class SendMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_LEN)
    # P2-4: per-turn model override for "Re-run with different model".
    # Doesn't persist to SessionMeta.model — applies to this turn only.
    # The SPA's user-message kebab → "Re-run with model X" hits POST
    # /messages with the original message text + a different `model`.
    model: str | None = Field(
        default=None,
        max_length=_MAX_MODEL_LEN,
        description=(
            "Optional per-turn model override (provider:model). When "
            "None, uses SessionMeta.model. The session's stored model "
            "is unchanged either way."
        ),
    )


class ArchiveResponse(BaseModel):
    ok: Literal[True] = True
    archived_at: datetime


class HistoryToolCall(BaseModel):
    """One tool call within a historic assistant turn.

    Sourced from the per-turn `.toolcalls.jsonl` sidecar we tee off the
    SSE stream at chat time. Mirrors the SPA's ToolCallSummary shape.
    """

    id: str
    name: str
    status: Literal["running", "done", "error"]
    args_preview: str | None = None
    result_preview: str | None = None


class HistoryMessage(BaseModel):
    """Single transcript turn rendered for the SPA.

    The kaos-agents wire format stores message items as
    `"user: <content>"` / `"assistant: <content>"` strings. We split
    role from content here so the SPA can render with the same
    Message component used for live-stream turns.
    """

    role: Literal["user", "assistant", "system"]
    content: str
    added_at: float
    # Populated only for assistant messages that had tool calls during
    # the turn. kaos-agents 0.1.0a1 doesn't persist trajectory data in
    # a shape we can hydrate, so we tee tool_call SSE events at chat
    # time into a per-turn sidecar; see app.services.tool_call_recorder.
    tool_calls: list[HistoryToolCall] = []


class HistoryResponse(BaseModel):
    session_id: str
    turn_count: int
    item_count: int
    messages: list[HistoryMessage]


# ── file uploads (P1-1, promoted to kaos_ui.uploads by P1-5) ──────────


# Re-export the canonical Pydantic shapes from kaos_ui.uploads so the
# FastAPI routes can keep using `response_model=FileMeta` unchanged.
# Identical fields; the only difference vs the previous definitions
# here is that the source-of-truth class lives in kaos-ui now and is
# shared with any other consumer.
from kaos_ui.uploads import FileMeta, FileParseStatus  # noqa: E402,F401


class UploadResponse(BaseModel):
    """POST /v1/chat/sessions/{id}/files response."""

    session_id: str
    file: FileMeta
    tools_enabled: bool = Field(
        description=(
            "Reflects the session's tools_enabled flag AFTER the upload. "
            "Uploading auto-flips this to True so the agent can use the "
            "read-only tool surface against the uploaded content."
        ),
    )


class FileListResponse(BaseModel):
    """GET /v1/chat/sessions/{id}/files response."""

    session_id: str
    files: list[FileMeta]


# ── citation extraction (P2-1) ────────────────────────────────────────


_MAX_CITATION_TEXT_LEN = 200_000


class ExtractCitationsBody(BaseModel):
    """POST /v1/chat/sessions/{id}/citations body.

    Used by the SPA to extract typed citations from an assistant turn
    once it lands. We cap at 200k chars — well above any realistic
    single-turn reply, and short of pathological abuse.
    """

    text: str = Field(min_length=1, max_length=_MAX_CITATION_TEXT_LEN)


class ExtractCitationsResponse(BaseModel):
    """POST /v1/chat/sessions/{id}/citations response.

    `citations` is a list of `Citation.model_dump()` shapes. The TS
    side uses a loose `Record<string, unknown>` since the kind union
    has 60+ variants — discriminator lives on `kind`.
    """

    session_id: str
    count: int
    citations: list[dict]


# ── corpus search (P2-3) ──────────────────────────────────────────────


class CorpusSearchHitWire(BaseModel):
    """One BM25 hit on the session's uploaded corpus."""

    filename: str
    score: float
    snippet: str = Field(description="First ~300 chars of the matching passage.")
    char_offset: int = Field(description="Byte offset within the source file's markdown.")


class CorpusSearchResponse(BaseModel):
    """GET /v1/chat/sessions/{id}/files/search response."""

    session_id: str
    query: str
    count: int
    hits: list[CorpusSearchHitWire]
