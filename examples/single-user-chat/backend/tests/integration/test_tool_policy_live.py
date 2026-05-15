"""TR-11 — live integration tests for ceiling enforcement + planner narrowing.

Tests through the real wire end-to-end:
  - Default ceiling (documents+citations+vfs) blocks kaos-source-* even
    when the user asks for live web data.
  - Opening the ceiling to include `web` + auto_narrow on lets the
    planner pick `web` and the agent uses kaos-source-fr-search.
  - When auto_narrow is off, the full ceiling is used every turn.

Requires a real Anthropic key (`SIMULATOR_ANTHROPIC_API_KEY` or
`ANTHROPIC_API_KEY`). Skipped on offline CI; gated on `live` marker.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.integration, pytest.mark.live]


def _skip_without_anthropic() -> None:
    if not (
        os.environ.get("SIMULATOR_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    ):
        pytest.skip("no Anthropic key available (live test)")


def _stream_events(response_text: str) -> list[dict]:
    """Parse the SSE response body into a list of decoded event payloads."""
    events: list[dict] = []
    for chunk in response_text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                raw = line[len("data: ") :]
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return events


def _send_message(client: TestClient, sid: str, message: str) -> list[dict]:
    """Drive POST /messages and return the parsed event stream."""
    with client.stream(
        "POST",
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": message},
    ) as resp:
        assert resp.status_code == 200, resp.read().decode()
        body = b"".join(resp.iter_bytes())
    return _stream_events(body.decode())


def _tool_names_from_turn(events: list[dict]) -> set[str]:
    """Names of every tool the agent attempted to call this turn."""
    for ev in events:
        if ev.get("type") == "turn_summary":
            return {tc["tool_name"] for tc in ev.get("tool_calls", [])}
    return set()


def _successful_tool_names_from_turn(events: list[dict]) -> set[str]:
    """Names of tools the agent SUCCESSFULLY called (is_error=False).

    The ceiling enforcement runs in the bridge layer — when the agent
    attempts a denied tool the call FAILS with is_error=True but still
    appears in tool_calls. The "did the ceiling enforce?" assertion is
    "no successful calls outside the ceiling".
    """
    for ev in events:
        if ev.get("type") == "turn_summary":
            return {
                tc["tool_name"] for tc in ev.get("tool_calls", []) if not tc.get("is_error")
            }
    return set()


def _tool_policy_event(events: list[dict]) -> dict | None:
    for ev in events:
        if ev.get("type") == "tool_policy_decided":
            return ev
    return None


# ── ceiling enforcement ──────────────────────────────────────────────


def test_default_ceiling_blocks_web_tools(client: TestClient) -> None:
    """A fresh session has documents+citations+vfs in the ceiling.
    Asking for a Federal Register search must NOT invoke kaos-source-*."""
    _skip_without_anthropic()

    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]

    events = _send_message(
        client, sid, "Search the Federal Register for the latest dairy regulation."
    )

    # The TurnToolPolicy planner must NOT narrow to a group outside
    # the ceiling. If the planner picked `web`, the intersection
    # with the ceiling drops it and we fall back to the ceiling.
    policy = _tool_policy_event(events)
    if policy is not None:
        assert "web" not in policy["turn_groups"], (
            f"turn_groups leaked outside ceiling: {policy['turn_groups']!r}"
        )

    # No SUCCESSFUL kaos-source-* call may happen — the ceiling
    # enforced at the proxy layer drops the tool from the catalog,
    # so any attempt by the agent fails with is_error=True. Failed
    # attempts are still listed in tool_calls; we filter to successful.
    successful = _successful_tool_names_from_turn(events)
    web_successes = {name for name in successful if name.startswith("kaos-source-")}
    assert web_successes == set(), (
        f"Expected no SUCCESSFUL kaos-source-* calls under default ceiling; "
        f"saw {web_successes!r}"
    )


def test_full_ceiling_with_auto_narrow_picks_web(client: TestClient) -> None:
    """A session with the full ceiling + auto_narrow on, asked an
    obvious web-search question, must narrow to ['web'] AND the agent
    must actually call a kaos-source-* tool."""
    _skip_without_anthropic()

    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]
    client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["documents", "citations", "vfs", "web"]},
    )

    events = _send_message(
        client,
        sid,
        "Use kaos-source-fr-search to find the latest dairy regulation in the Federal Register.",
    )

    policy = _tool_policy_event(events)
    assert policy is not None, "Expected tool_policy_decided event for auto_narrow session"
    assert "web" in policy["turn_groups"], (
        f"Planner should have picked web; got {policy['turn_groups']!r}"
    )

    successful = _successful_tool_names_from_turn(events)
    assert any(name.startswith("kaos-source-") for name in successful), (
        f"Expected a SUCCESSFUL kaos-source-* call; saw {successful!r}"
    )


def test_auto_narrow_off_keeps_full_ceiling(client: TestClient) -> None:
    """With auto_narrow=False the planner doesn't run; the agent sees
    the full ceiling regardless of message content."""
    _skip_without_anthropic()

    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]
    client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={
            "allowed_groups": ["documents", "citations", "vfs", "web"],
            "auto_narrow": False,
        },
    )

    events = _send_message(client, sid, "Hi, what tools can you use?")
    policy = _tool_policy_event(events)
    assert policy is None, "Expected no tool_policy_decided event when auto_narrow=False"


# ── deny floor ───────────────────────────────────────────────────────


def test_denied_tool_blocked_even_when_group_allowed(client: TestClient) -> None:
    """A tool in denied_tools is filtered even if its group is allowed
    at the ceiling. Defense in depth — user-toggleable allow-list never
    crosses the deny floor.
    """
    create = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = create.json()["id"]
    # Allow `web` but specifically deny kaos-source-fr-search.
    client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={
            "allowed_groups": ["documents", "citations", "vfs", "web"],
            "denied_tools": ["kaos-source-fr-search"],
            "auto_narrow": False,
        },
    )

    # Round-trip the tool_set to confirm the deny landed.
    meta = client.get(f"/v1/chat/sessions/{sid}/meta").json()
    assert "kaos-source-fr-search" in meta["tool_set"]["denied_tools"]
