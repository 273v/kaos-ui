"""#583 follow-up — corpus markdown must NOT advertise the ``.kaos.json``
AST sidecar path to the agent.

Pre-fix the system prompt's corpus-markdown block included two lines
per file:

    - VFS bytes: `sessions/{sid}/files/foo.docx`
    - VFS AST:   `sessions/{sid}/files/foo.docx.kaos.json`

gpt-5.4-mini interpreted the "VFS AST" path as a ready-to-use
artifact handle and fed it straight to ``kaos-content-stats``. That
tool takes an ``artifact_id`` (returned by ``kaos-office-parse-*``
/ ``kaos-pdf-extract-parse``), not a VFS path, so every attempt
errored with ``"Failed to load artifact ...: Unknown artifact"``.

For xlsx the failure compounds: ``parse_xlsx`` writes a
``TabularDocument`` JSON to the ``.kaos.json`` path, but content
tools expect ``ContentDocument`` — schema mismatch on top of the
artifact-vs-path mismatch.

Caught live in session 01KS7SWKDXWE3KDG2F5N2KJEW7 during the
release/0.1.1-spa Chrome MCP verification: error chip read
``Failed to load artifact 'sessions/.../files/states.xlsx.kaos.json':
Unknown artifact``.

Same family as #583's VFSList sidecar filter — the monkey-patch
caught the agent-listing surface, but the system-prompt corpus block
was a second surface that still leaked the path.

Post-fix: ``render_session_corpus_markdown`` emits only the VFS
bytes path, nudging the agent into the canonical chain:
``kaos-office-parse-docx(vfs_path)`` → artifact_id → content tools.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.unit
def test_corpus_markdown_omits_kaos_json_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rendered corpus markdown must NOT contain a ``.kaos.json``
    path. The agent picked the sidecar from this advertisement and
    tried to feed it to kaos-content-stats; the tool then errored
    with "Unknown artifact" on a malpractice-grade surface.
    """
    from kaos_ui.uploads import FileMeta, FileParseStatus

    from app.services import uploads as uploads_mod

    fake_metas = [
        FileMeta(
            filename="Toro 2022 Term Loan - Redline v1.docx",
            size_bytes=150_736,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            uploaded_at=datetime.now(UTC),
            parse=FileParseStatus(status="ready"),
            token_count=50_340,
            summary="A Term Loan Credit Agreement dated April 27, 2022.",
        ),
        FileMeta(
            filename="states.xlsx",
            size_bytes=20_654,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            uploaded_at=datetime.now(UTC),
            parse=FileParseStatus(status="ready"),
        ),
    ]

    async def fake_list(**kwargs: object) -> list[FileMeta]:
        return fake_metas

    monkeypatch.setattr(uploads_mod, "list_session_files", fake_list)

    runtime = MagicMock()
    markdown = asyncio.run(
        uploads_mod.render_session_corpus_markdown(
            runtime=runtime, session_id="01TESTSESSIONXXXXXXXXXX"
        )
    )

    # Negative: no .kaos.json mentions anywhere.
    assert ".kaos.json" not in markdown, (
        "regression: corpus markdown re-advertises the .kaos.json AST "
        "sidecar. The agent will feed it to content tools as an "
        f"artifact_id and fail with 'Unknown artifact'. Markdown was:\n{markdown}"
    )

    # Positive: bytes path IS present (that's the canonical entry for
    # kaos-office-parse-* / kaos-pdf-extract-parse).
    assert "VFS bytes:" in markdown, (
        "corpus markdown lost the VFS bytes line — agent now has no "
        f"path to feed the parse tools. Markdown was:\n{markdown}"
    )
    assert "sessions/01TESTSESSIONXXXXXXXXXX/files/states.xlsx" in markdown
    assert (
        "sessions/01TESTSESSIONXXXXXXXXXX/files/Toro 2022 Term Loan - Redline v1.docx"
        in markdown
    )


@pytest.mark.unit
def test_corpus_markdown_omits_meta_json_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Companion check: ``.meta.json`` sidecars (FileMeta-on-disk)
    also must not leak into the corpus markdown — same agent-confusion
    failure mode as ``.kaos.json``.
    """
    from kaos_ui.uploads import FileMeta, FileParseStatus

    from app.services import uploads as uploads_mod

    fake_metas = [
        FileMeta(
            filename="contract.pdf",
            size_bytes=1024,
            content_type="application/pdf",
            uploaded_at=datetime.now(UTC),
            parse=FileParseStatus(status="ready"),
        ),
    ]

    async def fake_list(**kwargs: object) -> list[FileMeta]:
        return fake_metas

    monkeypatch.setattr(uploads_mod, "list_session_files", fake_list)

    markdown = asyncio.run(
        uploads_mod.render_session_corpus_markdown(
            runtime=MagicMock(), session_id="01TESTSESSIONXXXXXXXXXX"
        )
    )

    assert ".meta.json" not in markdown, (
        f"corpus markdown leaks the .meta.json FileMeta sidecar: {markdown}"
    )
