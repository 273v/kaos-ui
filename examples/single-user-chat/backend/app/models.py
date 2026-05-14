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


class SessionSummary(BaseModel):
    """Lightweight row used in the sidebar list."""

    id: str
    title: str
    model: str
    last_message_at: datetime | None
    created_at: datetime
    message_count: int
    archived: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    next_cursor: str | None = None


# MEDIUM #3 — bounded inputs. Pre-fix, system_prompt was unbounded so a
# 10 MB persisted prompt + huge messages were possible. Bounds match the
# kaos-llm-client context-window floor (~32k tokens ≈ 100k chars), with
# headroom for the model + message and a single fixed turn budget.
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


class SendMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=_MAX_MESSAGE_LEN)


class ArchiveResponse(BaseModel):
    ok: Literal[True] = True
    archived_at: datetime


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


class HistoryResponse(BaseModel):
    session_id: str
    turn_count: int
    item_count: int
    messages: list[HistoryMessage]
