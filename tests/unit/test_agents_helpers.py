"""kaos_ui.agents — helper-level tests for the example's workarounds.

kaos-agents is not a runtime dep of kaos-ui (consuming apps install
it themselves), so tests that exercise the kaos-agents-touching
helpers are skipped when kaos-agents isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_ui.agents import (
    NO_TOOLS_PATTERN,
    augment_instructions,
)

_kaos_agents = pytest.importorskip(
    "kaos_agents",
    reason=(
        "kaos-agents not installed; helper-level tests run against the example's pinned version."
    ),
)

from kaos_ui.agents import (  # noqa: E402 — depends on the skip above
    build_chat_runtime,
    install_tool_bridge_runtime_patch,
)


def test_augment_instructions_when_tools_disabled() -> None:
    out = augment_instructions(
        base_prompt="Be terse.", tools_enabled=False, available_tool_names=None
    )
    assert "Tools are disabled" in out
    assert "Be terse." in out


def test_augment_instructions_when_tools_enabled_but_empty() -> None:
    out = augment_instructions(base_prompt="Be terse.", tools_enabled=True)
    assert "did not register any KAOS tools" in out


def test_augment_instructions_lists_available_tools() -> None:
    out = augment_instructions(
        base_prompt="Be helpful.",
        tools_enabled=True,
        available_tool_names=("kaos-pdf-parse", "kaos-core-vfs-list"),
    )
    assert "Be helpful." in out
    assert "Available KAOS tool names (2)" in out
    assert "- kaos-pdf-parse" in out
    assert "- kaos-core-vfs-list" in out


def test_no_tools_pattern_is_unmatchable_glob() -> None:
    """The sentinel must never match a real KAOS tool name."""
    assert NO_TOOLS_PATTERN.startswith("__")
    assert NO_TOOLS_PATTERN.endswith("__")


def test_install_tool_bridge_runtime_patch_is_idempotent() -> None:
    install_tool_bridge_runtime_patch()
    from kaos_agents.actions import tool_bridge  # ty: ignore[unresolved-import]

    assert tool_bridge._kaos_ui_patched is True
    # Calling again must not break the function.
    install_tool_bridge_runtime_patch()
    assert tool_bridge._kaos_ui_patched is True


def test_build_chat_runtime_returns_runtime_and_tools(tmp_path: Path) -> None:
    runtime, tool_names = build_chat_runtime(
        vfs_path=tmp_path / "vfs",
        register_extras=True,
        install_bridge_patch=False,  # tested separately
    )

    # Real disk-backed VFS, not memory.
    from kaos_core.vfs.models import StorageBackend

    assert runtime.vfs.config.default_backend == StorageBackend.DISK
    assert runtime.vfs.config.disk_base_path == (tmp_path / "vfs")

    # At least kaos-core tools are present.
    assert len(tool_names) > 0
    assert any(name.startswith("kaos-core-") for name in tool_names)


def test_build_chat_runtime_without_extras(tmp_path: Path) -> None:
    """register_extras=False must skip the pdf/office/content registrations."""
    _, names = build_chat_runtime(
        vfs_path=tmp_path / "vfs2",
        register_extras=False,
        install_bridge_patch=False,
    )
    # Tools only from kaos-core.
    assert all(not name.startswith("kaos-pdf-") for name in names)
    assert all(not name.startswith("kaos-office-") for name in names)
    assert all(not name.startswith("kaos-content-") for name in names)
