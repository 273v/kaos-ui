"""Pydantic API contracts for the Single-User Chat extension routes.

These are the shapes our `/v1/models` and `/v1/chat/*` endpoints accept
and return. The kaos-agents-owned `/v1/sessions/*` routes have their own
shapes (SessionCreateRequest, MessageRequest, etc.) defined in
kaos_agents.api.server — we don't redeclare those.

See docs/ARCHITECTURE.md § 3.3 for the design.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

Provider = Literal["anthropic", "openai", "google", "xai"]


# ── tool policy (TR-3) ────────────────────────────────────────────────


class SessionToolSetWire(BaseModel):
    """Per-session tool allow / deny policy — wire shape for SessionMeta.

    Round-trips through :class:`kaos_agents.types.SessionToolSet` via
    :meth:`to_session_tool_set`. JSON-friendly: lists instead of
    frozensets, ``default_factory`` for the "block everything except
    explicitly allowed groups" default.

    Semantics (resolves at proxy time, applied in
    :func:`kaos_agents.context.filter_tools`):

    1. ``allowed_groups`` empty → all groups pass the allow check.
    2. ``allowed_groups`` non-empty → tool's group must be in this set
       (groups from :data:`default_tool_group_registry`).
    3. ``denied_tools`` always wins — tools listed here are blocked
       even when their group is allowed.
    4. ``auto_narrow`` controls whether the per-turn TurnToolPolicy
       planner runs (TR-5). When false, the ceiling above is the
       effective tool set every turn.
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
    """

    id: str = Field(description="ULID, shared with the kaos-agents session_id")
    title: str
    model: str
    system_prompt: str
    # TR-3: tool_set is the source of truth for what the agent can call.
    # `tools_enabled` (below) is a derived view kept for one release so
    # the SPA can migrate without a flag day. Older meta sidecars that
    # only carry tools_enabled hydrate into the default ceiling
    # (documents+citations+vfs) — see `_migrate_tool_set` in
    # services/sessions.py.
    tool_set: SessionToolSetWire = Field(default_factory=SessionToolSetWire)
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
    def tools_enabled(self) -> bool:
        """Backward-compat derived view: True when ANY group is allowed.

        The SPA's existing "Enable read-only tools" checkbox reads
        this field. Until the SettingsSheet migrates to per-category
        toggles (TR-8), `tools_enabled=False` maps to "block all" and
        `tools_enabled=True` maps to "default ceiling".
        """
        return not self.tool_set.is_blocking_all

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_tools_enabled(cls, data: object) -> object:
        """Hydrate ``tool_set`` from a legacy ``tools_enabled`` bool.

        Old meta sidecars only carried ``tools_enabled: bool``. Without
        this migration, those files would silently lose the toggle on
        load (the bool would be discarded; ``tool_set`` would default
        to the standard ceiling regardless of what the user had
        chosen). Run only when ``tool_set`` is absent AND
        ``tools_enabled`` is present so live data isn't double-mapped.
        """
        if not isinstance(data, dict):
            return data
        if "tool_set" in data:
            # New shape — drop any stale tools_enabled key so the
            # computed_field is authoritative.
            data.pop("tools_enabled", None)
            return data
        legacy = data.pop("tools_enabled", None)
        if legacy is False:
            data["tool_set"] = {
                "allowed_groups": [],
                "denied_tools": [],
                "auto_narrow": True,
            }
        # legacy True or None → default ceiling (the field default).
        return data


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

    Both fields optional — pass only the dimension you're changing.
    ``allowed_groups`` empty list means "block all" (the session is
    fully read-only at the proxy layer).
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


class SendMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_LEN)


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
