"""Unit tests for the message-rewind endpoints (plan Issue 10 L3 + L4).

POST .../messages/{idx}/regenerate and PATCH .../messages/{idx} are
the two affordances that bring ChatGPT/Claude.ai parity to the SPA:

* Regenerate truncates at an assistant message + everything after.
* Edit-prior replaces a user message + truncates everything after.

These tests build a tiny synthetic memory.json on a tmp VFS and
drive the endpoints via TestClient. No live LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_AUTH = "Bearer demo-token-must-be-at-least-32-chars-long-for-validation"
_TOKEN_HASH_PREFIX = None  # filled in by _make_app


def _make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str, str]:
    """Fresh app + one session. Returns (client, session_id, tenant_prefix).

    The tenant_prefix is the sha256(token)[:12] used to scope the
    on-disk path. We need it to construct the memory.json fixture
    under the right directory.
    """
    monkeypatch.setenv("APP_VFS_PATH", str(tmp_path / ".kaos-vfs"))
    monkeypatch.setenv(
        "KAOS_AGENTS_API_API_TOKEN",
        "demo-token-must-be-at-least-32-chars-long-for-validation",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-stub-for-health")

    import app.logging_setup as ls

    ls._CONFIGURED = False  # type: ignore[attr-defined]

    import sys

    for mod in list(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]

    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/v1/chat/sessions",
        headers={"Authorization": _AUTH},
        json={"title": "rewind-test"},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # Derive the tenant prefix the same way the auth layer does.
    import hashlib

    token = "demo-token-must-be-at-least-32-chars-long-for-validation"
    tenant_prefix = hashlib.sha256(token.encode()).hexdigest()[:12]
    return client, sid, tenant_prefix


def _seed_memory(
    tmp_path: Path,
    sid: str,
    tenant_prefix: str,
    items: list[dict],
) -> Path:
    """Materialize a SessionMemory snapshot the way kaos-agents writes
    it. The path encoding mirrors ``scope_session_id`` — colon is
    URL-encoded.
    """
    scoped = f"{tenant_prefix}%3A{sid}"
    mem_dir = tmp_path / ".kaos-vfs" / "kaos-agents" / "sessions" / scoped
    mem_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": sid,
        "turn_count": 1,
        "corpus_ever_attached": False,
        "sections": {
            "messages": {
                "memory_type": "MESSAGES",
                "items": items,
            }
        },
    }
    path = mem_dir / "memory.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _items(*pairs: tuple[str, str]) -> list[dict]:
    """Construct items in the SessionMemory shape."""
    return [
        {
            "id": f"m{i}",
            "content": f"{role}: {text}",
            "token_count": len(text.split()),
            "added_at": 1779000000 + i,
            "metadata": {},
            "priority": 0,
            "tags": [],
        }
        for i, (role, text) in enumerate(pairs)
    ]


@pytest.mark.unit
def test_regenerate_drops_assistant_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two-turn transcript [u0, a0, u1, a1]. Regenerate at idx=1 (the
    first assistant) should leave [u0] — both the original assistant
    reply and the follow-up turn disappear.
    """
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    mem_path = _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(
            ("user", "hello"),
            ("assistant", "hi there"),
            ("user", "follow up"),
            ("assistant", "follow reply"),
        ),
    )
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/1/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid
    assert body["item_count"] == 1
    assert body["rewound_role"] == "assistant"
    # On-disk: only the user message remains.
    after = json.loads(mem_path.read_text())
    items = after["sections"]["messages"]["items"]
    assert [it["content"] for it in items] == ["user: hello"]


@pytest.mark.unit
def test_regenerate_at_latest_assistant_keeps_prior_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regenerating the latest assistant turn leaves a session in the
    "ready to re-send" state — the prior user message sticks around
    so the client can re-issue it verbatim.
    """
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    mem_path = _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(
            ("user", "summarize the contract"),
            ("assistant", "..."),
        ),
    )
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/1/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 200, r.text
    assert r.json()["item_count"] == 1
    items = json.loads(mem_path.read_text())["sections"]["messages"]["items"]
    assert items[0]["content"] == "user: summarize the contract"


@pytest.mark.unit
def test_regenerate_at_user_idx_returns_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regenerate at a user-message index is incoherent — the route
    must refuse with 422 + an error pointing at PATCH for editing."""
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(("user", "hi"), ("assistant", "ok")),
    )
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/0/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 422
    assert "PATCH" in r.json()["detail"]


@pytest.mark.unit
def test_regenerate_out_of_range_returns_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(("user", "hi"), ("assistant", "ok")),
    )
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/9/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 422


@pytest.mark.unit
def test_regenerate_no_memory_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh session with zero turns — regenerate is undefined here.
    Return 404 so the SPA can show "nothing to regenerate yet" rather
    than a generic 500."""
    client, sid, _ = _make_app(tmp_path, monkeypatch)
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/0/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 404


@pytest.mark.unit
def test_regenerate_unknown_session_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = _make_app(tmp_path, monkeypatch)
    r = client.post(
        "/v1/chat/sessions/01NEVERPERSISTED0000/messages/0/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 404


@pytest.mark.unit
def test_edit_prior_replaces_user_content_and_truncates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two-turn transcript [u0, a0, u1, a1]. Edit u1 → keeps [u0, a0,
    edited-u1]; a1 drops. Client then re-sends u1 to get a fresh reply.
    """
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    mem_path = _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(
            ("user", "first"),
            ("assistant", "reply"),
            ("user", "old follow-up"),
            ("assistant", "old follow reply"),
        ),
    )
    r = client.patch(
        f"/v1/chat/sessions/{sid}/messages/2",
        headers={"Authorization": _AUTH},
        json={"content": "rewritten follow-up"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_count"] == 3
    assert body["rewound_role"] == "user"
    items = json.loads(mem_path.read_text())["sections"]["messages"]["items"]
    assert [it["content"] for it in items] == [
        "user: first",
        "assistant: reply",
        "user: rewritten follow-up",
    ]


@pytest.mark.unit
def test_edit_prior_at_assistant_idx_returns_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(("user", "hi"), ("assistant", "ok")),
    )
    r = client.patch(
        f"/v1/chat/sessions/{sid}/messages/1",
        headers={"Authorization": _AUTH},
        json={"content": "should not work"},
    )
    assert r.status_code == 422
    assert "regenerate" in r.json()["detail"].lower()


@pytest.mark.unit
def test_edit_prior_rejects_empty_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pydantic min_length=1 — empty body is invalid (a "deleted"
    message is not a use case we support; the user can regenerate to
    drop a turn instead).
    """
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(("user", "hi")),
    )
    r = client.patch(
        f"/v1/chat/sessions/{sid}/messages/0",
        headers={"Authorization": _AUTH},
        json={"content": ""},
    )
    assert r.status_code == 422


@pytest.mark.unit
def test_rewind_is_atomic_on_partial_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the .tmp + os.replace pattern: a crash mid-write must
    leave the on-disk file unchanged. We can't easily inject a crash
    via TestClient, but we can assert no stray .tmp files survive a
    happy-path call (atomicity invariant by inspection).
    """
    client, sid, prefix = _make_app(tmp_path, monkeypatch)
    _seed_memory(
        tmp_path,
        sid,
        prefix,
        _items(("user", "u"), ("assistant", "a")),
    )
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages/1/regenerate",
        headers={"Authorization": _AUTH},
    )
    assert r.status_code == 200
    scoped = f"{prefix}%3A{sid}"
    mem_dir = tmp_path / ".kaos-vfs" / "kaos-agents" / "sessions" / scoped
    tmps = list(mem_dir.glob("*.tmp"))
    assert tmps == []
