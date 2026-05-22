"""Unit tests for the #583 monkey-patch in ``app/main.py`` that
strips SPA ``.kaos.json`` / ``.meta.json`` sidecars from the
agent-visible ``kaos-core-vfs-list`` result.

The patch installs at import time on ``app.main``; tests import
``app.main`` to trigger it, then exercise the patched
``VFSListTool.execute`` directly via a stub VFS + KaosRuntime.
"""

from __future__ import annotations

import pytest

import app.main  # noqa: F401 — import triggers monkey-patch install

from kaos_core.tools import VFSListTool


@pytest.mark.unit
def test_sidecar_filter_was_applied() -> None:
    assert getattr(VFSListTool, "_spa_sidecar_filter_applied", False) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filter_strips_kaos_json_sidecars() -> None:
    """Given a stub VFS that returns the original + both sidecars,
    the patched tool should hide both sidecars from the agent.
    """
    from kaos_core.base.context import KaosContext
    from kaos_core.vfs.models import VFSListPage

    raw_items = [
        "sessions/abc/files/Toro 2022 Term Loan - Redline v1.docx",
        "sessions/abc/files/Toro 2022 Term Loan - Redline v1.docx.kaos.json",
        "sessions/abc/files/Toro 2022 Term Loan - Redline v1.docx.meta.json",
        "sessions/abc/files/agreement.pdf",
        "sessions/abc/files/agreement.pdf.kaos.json",
        "sessions/abc/files/agreement.pdf.meta.json",
    ]

    class _StubVFS:
        async def list_page(self, path, *, limit, cursor, context_id):  # type: ignore[no-untyped-def]
            return VFSListPage(items=raw_items, next_cursor=None)

    class _StubRuntime:
        vfs = _StubVFS()

    context = KaosContext(
        session_id="abc",
        runtime=_StubRuntime(),
        vfs=_StubRuntime.vfs,
        default_vfs_namespace="sessions/abc/files/",
    )

    tool = VFSListTool()
    result = await tool.execute(inputs={"path": ""}, context=context)

    assert result.isError is False
    items = result.structuredContent["items"]
    # Original 6 items → 2 surviving (the actual files, no sidecars)
    assert items == [
        "sessions/abc/files/Toro 2022 Term Loan - Redline v1.docx",
        "sessions/abc/files/agreement.pdf",
    ]
    assert result.structuredContent["count"] == 2
    # Summary text lives at content[0].text for dict-shaped tool results
    assert result.content and "2 item(s)" in result.content[0].text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filter_passthrough_when_no_sidecars() -> None:
    """No sidecars in the list → result unchanged (same object identity
    where possible — patch returns the original ToolResult on no-op
    paths to keep the wire stable).
    """
    from kaos_core.base.context import KaosContext
    from kaos_core.vfs.models import VFSListPage

    raw_items = [
        "sessions/abc/files/agreement.pdf",
        "sessions/abc/files/memo.docx",
    ]

    class _StubVFS:
        async def list_page(self, path, *, limit, cursor, context_id):  # type: ignore[no-untyped-def]
            return VFSListPage(items=raw_items, next_cursor=None)

    class _StubRuntime:
        vfs = _StubVFS()

    context = KaosContext(
        session_id="abc",
        runtime=_StubRuntime(),
        vfs=_StubRuntime.vfs,
        default_vfs_namespace="sessions/abc/files/",
    )

    tool = VFSListTool()
    result = await tool.execute(inputs={"path": ""}, context=context)

    assert result.isError is False
    assert result.structuredContent["items"] == raw_items


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filter_preserves_error_results() -> None:
    """If the underlying VFS raises, the original error ToolResult must
    propagate unchanged (no filter attempted on the error path).
    """
    from kaos_core.base.context import KaosContext

    class _BadVFS:
        async def list_page(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("vfs is broken")

    class _StubRuntime:
        vfs = _BadVFS()

    context = KaosContext(
        session_id="abc",
        runtime=_StubRuntime(),
        vfs=_StubRuntime.vfs,
        default_vfs_namespace="sessions/abc/files/",
    )

    tool = VFSListTool()
    result = await tool.execute(inputs={"path": ""}, context=context)

    assert result.isError is True
    # Error message lives at content[0].text per ToolResult.create_error
    error_text = result.content[0].text if result.content else ""
    assert "vfs is broken" in error_text or "VFS list failed" in error_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filter_handles_mixed_subdirs() -> None:
    """Sidecars in subdirectories also get stripped — defensive check."""
    from kaos_core.base.context import KaosContext
    from kaos_core.vfs.models import VFSListPage

    raw_items = [
        "sessions/abc/files/foo.pdf",
        "sessions/abc/files/nested/bar.docx",
        "sessions/abc/files/nested/bar.docx.kaos.json",  # nested sidecar
    ]

    class _StubVFS:
        async def list_page(self, path, *, limit, cursor, context_id):  # type: ignore[no-untyped-def]
            return VFSListPage(items=raw_items, next_cursor=None)

    class _StubRuntime:
        vfs = _StubVFS()

    context = KaosContext(
        session_id="abc",
        runtime=_StubRuntime(),
        vfs=_StubRuntime.vfs,
        default_vfs_namespace="sessions/abc/files/",
    )

    tool = VFSListTool()
    result = await tool.execute(inputs={"path": ""}, context=context)
    assert result.isError is False
    assert (
        "sessions/abc/files/nested/bar.docx.kaos.json"
        not in result.structuredContent["items"]
    )
    assert "sessions/abc/files/nested/bar.docx" in result.structuredContent["items"]
