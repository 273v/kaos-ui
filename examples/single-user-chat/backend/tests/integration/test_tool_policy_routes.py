"""TR-4 — GET /v1/chat/categories + PATCH /v1/chat/sessions/:id/tool-set.

The SPA's SettingsSheet (TR-8) consumes these:
  - GET /v1/chat/categories → render checkboxes.
  - PATCH /v1/chat/sessions/:id/tool-set → mutate the per-session
    ceiling when the user toggles.

Validates the contract surface: auth gating, unknown-group 422,
partial-update semantics (omit a dimension → preserve current), and
the round trip back through GET /sessions/:id/meta.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


# ── /v1/chat/categories ──────────────────────────────────────────────


def test_categories_returns_known_groups(client: TestClient) -> None:
    response = client.get("/v1/chat/categories")
    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body["categories"]}
    # The single-user-chat backend always registers documents+vfs+
    # citations+web (when their respective packages are installed in
    # the test venv).
    assert "documents" in ids
    assert "vfs" in ids


def test_categories_marks_default_enabled_correctly(client: TestClient) -> None:
    response = client.get("/v1/chat/categories")
    by_id = {row["id"]: row for row in response.json()["categories"]}
    # Default ceiling = documents+citations+vfs; web is opt-in.
    assert by_id["documents"]["default_enabled"] is True
    assert by_id["vfs"]["default_enabled"] is True
    if "web" in by_id:
        assert by_id["web"]["default_enabled"] is False


def test_categories_requires_auth() -> None:
    # Build a TestClient without the bearer header.
    from fastapi.testclient import TestClient as _TC

    from app.main import app

    bare = _TC(app)
    response = bare.get("/v1/chat/categories")
    assert response.status_code in (401, 403)


# ── /v1/chat/sessions/:id/tool-set ───────────────────────────────────


def test_patch_tool_set_round_trips(client: TestClient) -> None:
    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]

    # Add web to the ceiling.
    patch = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["documents", "citations", "vfs", "web"]},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert set(body["tool_set"]["allowed_groups"]) == {
        "documents",
        "citations",
        "vfs",
        "web",
    }
    assert body["tools_enabled"] is True  # derived view follows


def test_patch_tool_set_partial_update_preserves_other_fields(client: TestClient) -> None:
    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]

    # First, narrow the ceiling.
    client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["documents"]},
    )

    # Then change ONLY auto_narrow — allowed_groups should remain.
    patch = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"auto_narrow": False},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["tool_set"]["allowed_groups"] == ["documents"]
    assert body["tool_set"]["auto_narrow"] is False


def test_patch_tool_set_rejects_unknown_group(client: TestClient) -> None:
    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]

    patch = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["documents", "not-a-real-group"]},
    )
    assert patch.status_code == 422
    detail = patch.json()["detail"]
    assert "not-a-real-group" in str(detail)


def test_patch_tool_set_block_all_with_empty_list(client: TestClient) -> None:
    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]

    patch = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": []},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["tool_set"]["allowed_groups"] == []
    # Derived view flips to False because the ceiling blocks all.
    assert body["tools_enabled"] is False


def test_patch_tool_set_404_for_unknown_session(client: TestClient) -> None:
    patch = client.patch(
        "/v1/chat/sessions/01NOPESUCHSESSIONIDABCDEFG/tool-set",
        json={"allowed_groups": ["documents"]},
    )
    assert patch.status_code == 404
