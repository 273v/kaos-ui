"""TR-3 — SessionMeta migrates legacy ``tools_enabled`` to ``tool_set``.

Old meta sidecars on disk only carry the boolean. Loading must
re-shape them into the new ``SessionToolSetWire``:
  - tools_enabled=False -> ceiling blocks everything (allowed_groups=[]).
  - tools_enabled=True / missing -> default ceiling.

The derived ``tools_enabled`` computed_field on the model must remain
truthful (mirror ``not tool_set.is_blocking_all``) for back-compat
with the SPA's existing checkbox.
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


def test_legacy_tools_enabled_true_maps_to_default_ceiling() -> None:
    raw = _base_meta_dict()
    raw["tools_enabled"] = True
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    # Default ceiling is documents+citations+vfs — web opt-in.
    assert set(meta.tool_set.allowed_groups) == {"documents", "citations", "vfs"}
    assert meta.tool_set.is_blocking_all is False
    assert meta.tools_enabled is True


def test_legacy_missing_tools_enabled_uses_default_ceiling() -> None:
    raw = _base_meta_dict()  # neither tool_set nor tools_enabled
    meta = SessionMeta.model_validate_json(json.dumps(raw))

    assert set(meta.tool_set.allowed_groups) == {"documents", "citations", "vfs"}
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


def test_session_tool_set_wire_default_is_default_ceiling() -> None:
    """The default for the field, not for the migration."""
    tool_set = SessionToolSetWire()
    assert set(tool_set.allowed_groups) == {"documents", "citations", "vfs"}
    assert tool_set.denied_tools == []
    assert tool_set.auto_narrow is True
    assert tool_set.is_blocking_all is False


def test_session_tool_set_wire_block_all_shape() -> None:
    """The "tools disabled" shape: empty allowed_groups."""
    tool_set = SessionToolSetWire(allowed_groups=[])
    assert tool_set.is_blocking_all is True
