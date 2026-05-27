"""#589 / B1.6 — corpus_attached → SessionMemory.DOCUMENTS live test.

Pre-fix: ``app/services/uploads.py`` wrote the corpus markdown into
the per-turn system prompt only. ``SessionMemory.DOCUMENTS`` stayed
empty, ``corpus_ever_attached`` stayed False, the IntentSignature
``corpus_attached`` signal never fired, and
``context/assemble.pin_corpus_handles`` was unreachable. Real
attorney symptom: agent ignored uploaded NDAs and answered from
training knowledge.

Post-fix: every successful upload writes a metadata headline to
``MemoryType.DOCUMENTS``. This test exercises the live wire by:

1. Creating a session via the real backend HTTP API.
2. POSTing an upload (real bytes, real disk write).
3. Querying the kaos-agents memory section endpoint and asserting
   the DOCUMENTS section item count went 0 → ≥1.

Uses TestClient so the SPA backend + kaos-agents wire run
in-process — same surface as a live curl.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_FIXTURE = Path("/home/mjbommar/projects/273v/kaos-office/tests/fixtures/xlsx/states.xlsx")
_AUTH = "Bearer demo-token-must-be-at-least-32-chars-long-for-validation"


@pytest.mark.integration
@pytest.mark.skipif(not _FIXTURE.exists(), reason="kaos-office xlsx fixture missing")
def test_upload_writes_to_session_memory_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live wire: upload → DOCUMENTS.item_count goes 0 → 1+."""
    # Isolate VFS to tmp_path so this test doesn't collide with the
    # running dev server's VFS or other test runs.
    monkeypatch.setenv("APP_VFS_PATH", str(tmp_path / "vfs"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-stub-for-health")
    monkeypatch.setenv(
        "KAOS_AGENTS_API_API_TOKEN",
        "demo-token-must-be-at-least-32-chars-long-for-validation",
    )

    # IMPORTANT: re-import app.main + reset configure flag so the
    # AppSettings re-reads APP_VFS_PATH.
    import app.logging_setup as ls

    ls._CONFIGURED = False  # type: ignore[attr-defined]

    # Drop cached app module so the next import sees fresh env.
    import sys

    for mod in list(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]

    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    # 1. Create session
    r = client.post(
        "/v1/chat/sessions",
        headers={"Authorization": _AUTH},
        json={"title": "B1.6 corpus_attached signal test"},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # 2. Upload xlsx (real bytes, real parse)
    with _FIXTURE.open("rb") as fh:
        r = client.post(
            f"/v1/chat/sessions/{sid}/files",
            headers={"Authorization": _AUTH},
            files={"file": (_FIXTURE.name, fh, "application/vnd.ms-excel")},
        )
    assert r.status_code == 201, r.text
    upload_body = r.json()
    assert upload_body["file"]["parse"]["status"] == "ready"

    # 3. Query DOCUMENTS section directly via the runtime's
    # SessionStore (same path agent_loop reads from). Reading via
    # the kaos-agents wire would be ideal but requires routing
    # config to the agent's API surface; in-process read of the
    # same VFS + SessionStore is equivalent for the contract test.
    import asyncio

    async def _check():
        from kaos_agents.api.settings import scope_session_id
        from kaos_agents.memory.store import SessionStore
        from kaos_agents.types.memory import MemoryType

        runtime = app.state.kaos_runtime
        # Upload handler computes tenant_id via require_auth →
        # ``app.state.api_settings.tenant_id()`` (sha256(token)[:12])
        # so the scope_session_id path is ``{tenant_hash}:{sid}``.
        # Test verification must use the same scope or it reads a
        # different memory.json file.
        api_settings = app.state.api_settings
        tenant_id = api_settings.tenant_id()
        effective_sid = scope_session_id(sid, tenant_id)
        store = SessionStore(runtime.vfs)
        memory = await store.load_or_create(effective_sid)
        return (
            memory.section_item_count(MemoryType.DOCUMENTS),
            memory.get(MemoryType.DOCUMENTS),
        )

    count, items = asyncio.run(_check())
    assert count >= 1, (
        f"B1.6 regression: DOCUMENTS.item_count expected ≥1 after upload, "
        f"got {count}. Items: {items}"
    )
    # Spot-check: the headline mentions the filename
    assert any(_FIXTURE.name in (it.content or "") for it in items), (
        f"DOCUMENTS items don't reference uploaded filename: {[it.content for it in items]}"
    )
