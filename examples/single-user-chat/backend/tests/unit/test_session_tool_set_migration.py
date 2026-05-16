"""SessionMeta back-compat migration over three historic shapes.

Historic on-disk shapes (oldest → newest):

1. Pre-TR-3: ``tools_enabled: bool`` only.
2. TR-3 (kaos-agents 0.1.0a2): ``tool_set: SessionToolSetWire``.
3. AgenticLoop (kaos-agents 0.1.0a4): ``policy: SessionPolicyWire``.

Loading must re-shape any of the above into the canonical
``policy: SessionPolicyWire`` while keeping the derived
``tool_set`` computed_field and the bool ``tools_enabled`` view
in sync for SPA clients that haven't cut over yet.

State 1 (legacy bool) mapping:
  - ``tools_enabled=False`` -> ceiling blocks everything (allowed_groups=[]).
  - ``tools_enabled=True`` / missing -> research persona default.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.models import SessionMeta, SessionToolSetWire


def _base_meta_dict() -> dict:
    return {
        "id": "01J1234567890123456789ABCD",
        "title": "test",
        "model": "anthropic:claude-haiku-4-5",
        "system_prompt": "Be helpful.",
        "created_at": datetime(2026, 5, 14, tzinfo=UTC).isoformat(),
        "last_message_at": None,
        "message_count": 0,
        "archived": False,
        "starred": False,
        "title_source": "auto",
        "title_updated_at": None,
    }


def test_legacy_tools_enabled_false_maps_to_blocked_ceiling() -> None:
    raw = _base_meta_dict()
    raw["tools_enabled"] = False
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    assert meta.tool_set.allowed_groups == []
    assert meta.tool_set.is_blocking_all is True
    # Derived back-compat view must still report False.
    assert meta.tools_enabled is False


_RESEARCH_DEFAULT_GROUPS = {
    "web",
    "browser",
    "netinfra",
    "documents",
    "citations",
    "vfs",
    "forensics",
    "retrieval",
}


def test_legacy_tools_enabled_true_maps_to_default_ceiling() -> None:
    raw = _base_meta_dict()
    raw["tools_enabled"] = True
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    # New default ceiling = research persona's allowed_groups (8 groups).
    # The pre-AgenticLoop default (documents+citations+vfs) was widened
    # so that the loop has room to auto-narrow per-turn instead of
    # forcing the user to opt in to every group up front.
    assert set(meta.tool_set.allowed_groups) == _RESEARCH_DEFAULT_GROUPS
    assert meta.tool_set.is_blocking_all is False
    assert meta.tools_enabled is True


def test_legacy_missing_tools_enabled_uses_default_ceiling() -> None:
    raw = _base_meta_dict()  # neither tool_set nor tools_enabled
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    assert set(meta.tool_set.allowed_groups) == _RESEARCH_DEFAULT_GROUPS
    assert meta.tools_enabled is True


def test_explicit_tool_set_wins_over_legacy_bool() -> None:
    """When both shapes are present, tool_set is authoritative; bool ignored.

    Defensive — should never happen in real round-trips but the
    migration must not double-map.
    """
    raw = _base_meta_dict()
    raw["tools_enabled"] = True  # would map to default ceiling
    raw["tool_set"] = {
        "allowed_groups": ["web"],
        "denied_tools": [],
        "auto_narrow": False,
    }
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    assert meta.tool_set.allowed_groups == ["web"]
    assert meta.tool_set.auto_narrow is False
    assert meta.tools_enabled is True


def test_round_trip_preserves_tool_set_shape() -> None:
    """model_dump -> model_validate must be lossless."""
    raw = _base_meta_dict()
    raw["tool_set"] = {
        "allowed_groups": ["documents", "web"],
        "denied_tools": ["kaos-office-write-docx"],
        "auto_narrow": False,
    }
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    redumped = meta.model_dump_json()
    meta2 = SessionMeta.model_validate_json(redumped)

    assert meta2.tool_set.allowed_groups == ["documents", "web"]
    assert meta2.tool_set.denied_tools == ["kaos-office-write-docx"]
    assert meta2.tool_set.auto_narrow is False


def test_computed_tools_enabled_is_read_only() -> None:
    """The derived view cannot be mutated directly — caller writes
    flow through tool_set or the persistence layer's bool sugar."""
    raw = _base_meta_dict()
    raw["tools_enabled"] = True
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    with pytest.raises((AttributeError, ValueError)):
        meta.tools_enabled = False  # type: ignore[misc]


def test_session_tool_set_wire_default_is_legacy_default_ceiling() -> None:
    """The legacy SessionToolSetWire field default — pre-AgenticLoop shape.

    SessionToolSetWire is now LEGACY; new sessions persist
    SessionPolicyWire directly. The class survives only so the
    SPA back-compat `tool_set` computed_field on SessionMeta has
    something to return. Its own default keeps the original
    documents+citations+vfs trio (web opt-in) so existing tests +
    SPA flows that construct one directly behave unchanged.
    """
    tool_set = SessionToolSetWire()
    assert set(tool_set.allowed_groups) == {"documents", "citations", "vfs"}
    assert tool_set.denied_tools == []
    assert tool_set.auto_narrow is True
    assert tool_set.is_blocking_all is False


def test_session_tool_set_wire_block_all_shape() -> None:
    """The "tools disabled" shape: empty allowed_groups."""
    tool_set = SessionToolSetWire(allowed_groups=[])
    assert tool_set.is_blocking_all is True
