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
    KAOS_TOOL_GROUP_DESCRIPTIONS,
    KAOS_TOOL_GROUP_PREFIXES,
    build_chat_runtime,
    install_tool_bridge_runtime_patch,
    register_kaos_tool_groups,
)


def test_augment_instructions_when_tools_disabled() -> None:
    out = augment_instructions(base_prompt="Be terse.", tools_enabled=False)
    assert "Tools are disabled" in out
    assert "Be terse." in out


def test_augment_instructions_when_tools_enabled_returns_date_plus_base() -> None:
    """Tools-enabled path returns date preamble + base only.

    The tool catalog is delivered to the LLM via the provider's native
    tool-use API (kaos-agents 0.1.0a5+ ReAct path), so inlining it
    into the system prompt is redundant. See
    ``kaos-modules/docs/plans/thin-worker-prompt.md`` §4.5 (M5).
    """
    out = augment_instructions(base_prompt="Be helpful.", tools_enabled=True)
    assert "Be helpful." in out
    assert "## TODAY IS" in out
    # No catalog block, no enabled-tools sentinel — the provider's
    # native tools= surface is the source of truth.
    assert "Available KAOS tool names" not in out
    assert "did not register any KAOS tools" not in out


def test_augment_instructions_does_not_inline_tool_names() -> None:
    """Tool names must not appear anywhere in the rendered prompt.

    Regression guard against re-introducing the catalog block.
    """
    out = augment_instructions(base_prompt="Be helpful.", tools_enabled=True)
    for name in ("kaos-pdf-parse", "kaos-core-vfs-list", "kaos-source-fetch-url"):
        assert name not in out


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


# ── tool-group registration (TR-1) ───────────────────────────────────


def test_tool_group_prefix_table_is_well_formed() -> None:
    """Each prefix maps to a known group, and longer prefixes precede
    shorter ones so ``kaos-core-vfs-`` wins over a hypothetical
    ``kaos-core-`` catchall."""
    for prefix, group in KAOS_TOOL_GROUP_PREFIXES:
        assert prefix.startswith("kaos-")
        assert prefix.endswith("-")
        assert group in KAOS_TOOL_GROUP_DESCRIPTIONS, (
            f"prefix {prefix} -> {group} but group has no description"
        )

    # Order check: any longer prefix that shares a stem with a shorter
    # one must appear FIRST so ``startswith`` matches the more specific
    # group. The current table has kaos-core-vfs- before kaos-core- (if
    # the catchall ever returns); guard so the discipline is preserved.
    seen: list[str] = []
    for prefix, _ in KAOS_TOOL_GROUP_PREFIXES:
        for earlier in seen:
            assert not earlier.startswith(prefix), (
                f"prefix {prefix} is a stem of earlier {earlier}; reorder"
            )
        seen.append(prefix)


def test_register_kaos_tool_groups_partitions_kaos_core_tools(tmp_path: Path) -> None:
    """A runtime with only kaos-core registered should land its vfs +
    artifact tools in the ``vfs`` group and no others."""
    from kaos_agents.registry import default_tool_group_registry  # ty: ignore[unresolved-import]

    default_tool_group_registry.clear()  # isolate from prior state
    runtime, _ = build_chat_runtime(
        vfs_path=tmp_path / "vfs",
        register_extras=False,
        install_bridge_patch=False,
    )
    counts = register_kaos_tool_groups(runtime)

    # kaos-core registers kaos-core-vfs-* + kaos-core-artifacts-* —
    # those should all land in `vfs`. `web`, `documents`, `citations`
    # remain empty and must be omitted from counts (not zero-entries).
    assert "vfs" in counts
    assert counts["vfs"] >= 1
    assert "web" not in counts
    assert "documents" not in counts
    assert "citations" not in counts

    vfs_group = default_tool_group_registry.get("vfs")
    assert vfs_group is not None
    assert all(
        name.startswith("kaos-core-vfs-") or name.startswith("kaos-core-artifacts-")
        for name in vfs_group.tool_names
    )


def test_register_kaos_tool_groups_is_idempotent(tmp_path: Path) -> None:
    """Re-running picks up newly-registered tools and never raises on
    name collision (force=True path)."""
    from kaos_agents.registry import default_tool_group_registry  # ty: ignore[unresolved-import]

    default_tool_group_registry.clear()
    runtime, _ = build_chat_runtime(
        vfs_path=tmp_path / "vfs",
        register_extras=True,  # pdf/office/content -> documents
        install_bridge_patch=False,
    )
    first = register_kaos_tool_groups(runtime)
    # Re-run must not raise even though groups are already registered.
    second = register_kaos_tool_groups(runtime)
    assert first == second


def test_register_kaos_tool_groups_groups_documents(tmp_path: Path) -> None:
    """kaos-pdf / kaos-office-parse / kaos-content all land in the
    same `documents` group, so user-facing `enable documents` is a
    single decision."""
    from kaos_agents.registry import default_tool_group_registry  # ty: ignore[unresolved-import]

    default_tool_group_registry.clear()
    runtime, names = build_chat_runtime(
        vfs_path=tmp_path / "vfs",
        register_extras=True,
        install_bridge_patch=False,
    )
    register_kaos_tool_groups(runtime)
    docs = default_tool_group_registry.get("documents")
    assert docs is not None
    # Documents group should contain at least one tool from each of
    # the three document-handling modules when they're installed.
    # We don't hard-pin counts because the upstream catalogs evolve;
    # we just verify the membership invariant.
    if any(n.startswith("kaos-pdf-") for n in names):
        assert any(t.startswith("kaos-pdf-") for t in docs.tool_names)
    if any(n.startswith("kaos-content-") for n in names):
        assert any(t.startswith("kaos-content-") for t in docs.tool_names)
