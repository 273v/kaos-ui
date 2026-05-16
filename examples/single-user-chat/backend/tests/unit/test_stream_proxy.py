"""Unit tests for the chat-to-kaos-agents stream proxy request body."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kaos_ui.agents import NO_TOOLS_PATTERN

from app.models import SessionMeta, SessionPolicyWire
from app.services.stream_proxy import _build_forward_body

pytestmark = pytest.mark.unit


def _meta(*, tools_enabled: bool) -> SessionMeta:
    now = datetime.now(UTC)
    if tools_enabled:
        policy = SessionPolicyWire.for_persona("research")
    else:
        policy = SessionPolicyWire(
            allowed_groups=[],
            soft_ceiling=[],
            denied_tools=[],
            persona="research",
        )
    return SessionMeta(
        id="s1",
        title="Test",
        model="anthropic:claude-haiku-4-5",
        system_prompt="Base instructions.",
        policy=policy,
        created_at=now,
        last_message_at=now,
        message_count=0,
    )


def test_forward_body_disables_tools_with_no_match_filter() -> None:
    body = _build_forward_body(_meta(tools_enabled=False), "hello", 0.5)

    assert body["tools"] == [NO_TOOLS_PATTERN]
    assert "Tools are disabled for this session" in body["instructions"]


def test_forward_body_enables_tools_with_session_tool_set_filter() -> None:
    """TR-2: tools_enabled=True must resolve the SessionMeta.tool_set
    ceiling (default = documents + citations + vfs) against the runtime
    catalog and forward only the matching tool names, not a wildcard."""
    from kaos_agents.registry import default_tool_group_registry
    from kaos_agents.types import ToolGroup

    # Register groups so the proxy can resolve allowed_groups -> names.
    default_tool_group_registry.clear()
    default_tool_group_registry.register(
        ToolGroup(
            name="documents",
            description="parsing",
            tool_names=("kaos-pdf-search-document",),
        )
    )
    default_tool_group_registry.register(
        ToolGroup(
            name="vfs",
            description="vfs",
            tool_names=("kaos-core-list-tools",),
        )
    )

    body = _build_forward_body(
        _meta(tools_enabled=True),
        "what tools can you use",
        0.5,
        # Catalog contains one allowed tool (in `documents`) plus one
        # that is not in any registered group (should be excluded by
        # the SessionToolSet's allowed_groups filter).
        available_tool_names=(
            "kaos-pdf-search-document",
            "kaos-core-list-tools",
            "kaos-tabular-query",  # no group registered → excluded
        ),
    )

    # Only the tools whose group is in the default ceiling
    # (documents + citations + vfs) pass through.
    assert set(body["tools"]) == {"kaos-pdf-search-document", "kaos-core-list-tools"}
    assert "kaos-tabular-query" not in body["tools"]
    assert "*" not in body["tools"]
    # The system prompt still names every tool in the catalog (the
    # available_tool_names argument is the un-filtered list — the
    # filtering happens at the wire layer).
    assert "Available KAOS tool names (3)" in body["instructions"]


def test_forward_body_falls_back_to_group_globs_without_catalog() -> None:
    """When no available_tool_names is supplied, the proxy can't
    enumerate the catalog. It falls back to group-prefix globs so the
    ceiling is still applied (bridge-side fnmatch enforces from there).

    Note: post-AgenticLoop the default ceiling is the research persona's
    8-group set ({web, browser, netinfra, documents, citations, vfs,
    forensics, retrieval}). Only the groups present in
    ``_GROUP_GLOBS`` contribute fallback globs — unmapped groups
    (browser, netinfra, forensics, retrieval) are no-ops on this path
    because the real enforcement runs through the AgenticLoop +
    bridge fnmatch.
    """
    body = _build_forward_body(
        _meta(tools_enabled=True),
        "hi",
        0.5,
        # No available_tool_names → fallback path.
    )

    # Research-persona default ceiling expands to the mapped subset of
    # _GROUP_GLOBS (web + documents + citations + vfs).
    expected_prefixes = {
        "kaos-source-*",
        "kaos-pdf-*",
        "kaos-office-parse-*",
        "kaos-content-*",
        "kaos-citations-*",
        "kaos-core-vfs-*",
        "kaos-core-artifacts-*",
    }
    assert set(body["tools"]) == expected_prefixes


def test_readonly_allowlist_excludes_write_globs() -> None:
    """Belt+suspenders — the curated allowlist must NOT contain a
    universal wildcard or any name suggestive of writes."""
    from app.services.catalog import READ_ONLY_TOOL_GLOBS

    assert "*" not in READ_ONLY_TOOL_GLOBS
    assert "**" not in READ_ONLY_TOOL_GLOBS
    forbidden_substrings = ("write", "delete", "rm", "send", "upload", "edit", "modify")
    for glob in READ_ONLY_TOOL_GLOBS:
        low = glob.lower()
        for bad in forbidden_substrings:
            assert bad not in low, f"allowlist glob {glob!r} contains forbidden substring {bad!r}"
