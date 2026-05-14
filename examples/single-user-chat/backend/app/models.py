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

from pydantic import BaseModel, Field

Provider = Literal["anthropic", "openai", "google", "xai"]


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
    tools_enabled: bool = False
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


# ── file uploads (P1-1) ───────────────────────────────────────────────


class FileParseStatus(BaseModel):
    """Parse outcome for one uploaded file.

    ``ready`` means the file was parsed and a `.kaos.json` AST sidecar
    exists in the VFS alongside the original bytes. ``failed`` means
    parsing raised — the original bytes were still saved.
    """

    status: Literal["ready", "failed"]
    error: str | None = None


class FileMeta(BaseModel):
    """Per-file metadata persisted alongside the upload in the VFS.

    Lives at ``sessions/{session_id}/files/{filename}.meta.json``.
    """

    filename: str
    size_bytes: int
    content_type: str | None = None
    uploaded_at: datetime
    parse: FileParseStatus
    # Populated post-parse via kaos-nlp-core + kaos-llm-core. Both are
    # best-effort — a parse failure or summarizer outage leaves them
    # null, but the file is still persisted.
    token_count: int | None = None
    summary: str | None = None


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
