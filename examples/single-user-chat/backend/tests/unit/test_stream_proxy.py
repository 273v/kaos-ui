"""Unit tests for the chat-to-kaos-agents stream proxy request body."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import SessionMeta
from app.services.stream_proxy import _NO_TOOLS_PATTERN, _build_forward_body

pytestmark = pytest.mark.unit


def _meta(*, tools_enabled: bool) -> SessionMeta:
    now = datetime.now(UTC)
    return SessionMeta(
        id="s1",
        title="Test",
        model="anthropic:claude-haiku-4-5",
        system_prompt="Base instructions.",
        tools_enabled=tools_enabled,
        created_at=now,
        last_message_at=now,
        message_count=0,
    )


def test_forward_body_disables_tools_with_no_match_filter() -> None:
    body = _build_forward_body(_meta(tools_enabled=False), "hello", 0.5)

    assert body["tools"] == [_NO_TOOLS_PATTERN]
    assert "Tools are disabled for this session" in body["instructions"]


def test_forward_body_enables_all_tools_and_includes_catalog() -> None:
    body = _build_forward_body(
        _meta(tools_enabled=True),
        "what tools can you use",
        0.5,
        available_tool_names=("kaos-pdf-search-document", "kaos-core-list-tools"),
    )

    assert body["tools"] == ["*"]
    assert "Available KAOS tool names (2)" in body["instructions"]
    assert "- kaos-core-list-tools" in body["instructions"]
    assert "- kaos-pdf-search-document" in body["instructions"]
