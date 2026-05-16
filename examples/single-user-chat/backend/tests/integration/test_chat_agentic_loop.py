"""Chat router → AgenticLoop integration (no LLM).

These tests stub :func:`kaos_agents.patterns.agentic_loop.run_agentic_turn`
with a deterministic generator and assert that the chat router's
``POST /v1/chat/sessions/{id}/messages`` SSE response correctly:

  1. Builds a :class:`SessionPolicy` from the session's stored
     :class:`SessionPolicyWire` and hands it to the loop.
  2. Threads the persona, available_groups, and corpus_headlines.
  3. Forwards loop-emitted :class:`KaosEvent` objects as SSE records
     with the discriminator ``type`` injected into the JSON payload.
  4. Forwards worker-emitted SSE dicts verbatim (no double-wrapping).
  5. Bumps ``message_count`` by 2 on a successful turn.

These are the canonical regression checks for the L.5 wire-up. The
real LLM-calling integration tests live in N.1+ (the "agent must
never give up on a searchable question" suite).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _emit_turn(captured: dict[str, Any]) -> AsyncIterator[Any]:
    """Build a deterministic event stream mirroring a real run_agentic_turn.

    Yields, in order:
      1. A worker-shaped SSE dict (text_delta)
      2. A typed KaosEvent (GoalChecked)
      3. A typed KaosEvent (LoopTerminated)
    """
    from kaos_agents.events.policy import GoalChecked, LoopTerminated

    async def _gen() -> AsyncIterator[Any]:
        # Worker-shaped event (already SSE-shaped, gets forwarded verbatim).
        yield {
            "event": "text_delta",
            "data": json.dumps({"type": "text_delta", "content": "Hello "}),
        }
        yield {
            "event": "text_delta",
            "data": json.dumps({"type": "text_delta", "content": "world."}),
        }
        # Typed KaosEvents — chat router must serialize via .model_dump.
        yield GoalChecked(
            timestamp=0.0,
            sequence=1,
            session_id=captured.get("session_id", ""),
            run_id=captured.get("run_id", ""),
            kind="satisfied",
            rationale="The answer addresses the user's question.",
            confidence=0.92,
            iteration=1,
            cost_usd=0.001,
            latency_ms=120.0,
        )
        yield LoopTerminated(
            timestamp=0.0,
            sequence=2,
            session_id=captured.get("session_id", ""),
            run_id=captured.get("run_id", ""),
            reason="satisfied",
            iterations_used=1,
            elevations_used=0,
            cost_usd=0.005,
            wall_clock_ms=300.0,
        )

    return _gen()


def _patch_agentic_turn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace run_agentic_turn with a capturing stub. Returns the captured-kwargs dict."""
    captured: dict[str, Any] = {}

    def _fake(**kwargs: Any) -> AsyncIterator[Any]:
        captured.update(kwargs)
        return _emit_turn(kwargs)

    import kaos_agents.patterns.agentic_loop as agentic_module

    monkeypatch.setattr(agentic_module, "run_agentic_turn", _fake)
    return captured


def _parse_sse(body: str) -> list[dict[str, str]]:
    """Parse a TestClient SSE response body into ``[{event, data}, ...]``."""
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in body.splitlines():
        if not line.strip():
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith(":"):
            continue  # comment / ping
        key, _, value = line.partition(":")
        if not value.startswith(" "):
            current[key.strip()] = value
        else:
            current[key.strip()] = value[1:]
    if current:
        events.append(current)
    return events


def _create_session(client: TestClient, *, tools_enabled: bool = True) -> str:
    r = client.post(
        "/v1/chat/sessions",
        json={
            "model": "anthropic:claude-haiku-4-5",
            "tools_enabled": tools_enabled,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_router_forwards_worker_dict_events_verbatim(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_agentic_turn(monkeypatch)
    sid = _create_session(client)

    r = client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)

    # Worker-shaped events ride through with the same `event:` name and
    # `data:` JSON the stub emitted.
    text_deltas = [e for e in events if e.get("event") == "text_delta"]
    assert len(text_deltas) == 2
    assert json.loads(text_deltas[0]["data"])["content"] == "Hello "
    assert json.loads(text_deltas[1]["data"])["content"] == "world."

    # The captured-kwargs proves we routed through run_agentic_turn.
    assert captured["session_id"] == sid
    assert captured["run_id"].startswith("turn-")


def test_router_serializes_kaos_events_with_type_discriminator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typed KaosEvent objects from run_agentic_turn must arrive at the
    SPA as ``{event: <type>, data: '{..., "type": "<type>"}'}``.

    The SPA's reducer switches on ``payload.type``, so the discriminator
    must be present inside the JSON body — KaosEvent stores it as a
    ClassVar, not a field, so the router injects it explicitly.
    """
    _patch_agentic_turn(monkeypatch)
    sid = _create_session(client)

    r = client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 200
    events = _parse_sse(r.text)

    goal_checked = next((e for e in events if e.get("event") == "goal_checked"), None)
    assert goal_checked is not None, "Expected a goal_checked SSE event"
    payload = json.loads(goal_checked["data"])
    assert payload["type"] == "goal_checked"
    assert payload["kind"] == "satisfied"
    assert payload["confidence"] == 0.92

    loop_term = next((e for e in events if e.get("event") == "loop_terminated"), None)
    assert loop_term is not None
    payload = json.loads(loop_term["data"])
    assert payload["type"] == "loop_terminated"
    assert payload["reason"] == "satisfied"
    assert payload["iterations_used"] == 1


def test_router_passes_session_policy_into_loop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_agentic_turn(monkeypatch)
    sid = _create_session(client, tools_enabled=True)

    r = client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 200

    # The SessionPolicy from kaos-agents (the value type) must reach the loop.
    from kaos_agents.types.session_policy import SessionPolicy

    policy = captured["policy"]
    assert isinstance(policy, SessionPolicy)
    # Default research persona — 8 groups (web/browser/netinfra/...).
    assert "web" in policy.allowed_groups
    assert "documents" in policy.allowed_groups
    # Persona threaded into the planner Signature as `session_intent`.
    assert captured["session_intent"] == "research"
    # available_groups must be the registry's full list (planner needs
    # to know what's actually registered, not just what's allowed).
    assert isinstance(captured["available_groups"], list)
    assert len(captured["available_groups"]) > 0


def test_router_passes_available_groups_and_corpus_headlines(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _patch_agentic_turn(monkeypatch)
    sid = _create_session(client)

    client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "hi"})
    # `corpus_headlines` is always supplied even when empty.
    assert "corpus_headlines" in captured
    assert isinstance(captured["corpus_headlines"], str)


def test_message_count_increments_on_successful_turn(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_agentic_turn(monkeypatch)
    sid = _create_session(client)

    before = client.get(f"/v1/chat/sessions/{sid}/meta").json()
    assert before["message_count"] == 0

    r = client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 200

    after = client.get(f"/v1/chat/sessions/{sid}/meta").json()
    # Bumped by exactly 2 (user message + assistant reply == 1 turn).
    assert after["message_count"] == 2


def test_blocked_session_still_routes_through_agentic_loop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session with ``tools_enabled=False`` still uses the AgenticLoop —
    the loop just sees an empty ``allowed_groups`` and the worker reports
    a tool-less reply. The router does NOT short-circuit the loop based
    on the ceiling state.
    """
    captured = _patch_agentic_turn(monkeypatch)
    sid = _create_session(client, tools_enabled=False)

    r = client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "hi"})
    assert r.status_code == 200

    from kaos_agents.types.session_policy import SessionPolicy

    policy = captured["policy"]
    assert isinstance(policy, SessionPolicy)
    # Block-all = empty ceiling.
    assert len(policy.allowed_groups) == 0


def test_run_id_encodes_pre_turn_message_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run_id encodes ``message_count // 2`` measured BEFORE the
    turn — so the very first turn gets ``turn-0`` and the SPA's
    tool-call sidecar lookup stays consistent."""
    captured = _patch_agentic_turn(monkeypatch)
    sid = _create_session(client)

    r = client.post(f"/v1/chat/sessions/{sid}/messages", json={"message": "first"})
    assert r.status_code == 200
    assert captured["run_id"] == "turn-0"


def test_attached_files_force_documents_and_vfs_into_policy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F.11.A regression — when at least one file is attached to the
    session, the chat router must widen the SessionPolicy's
    ``allowed_groups`` (and ``soft_ceiling``) to include
    ``documents`` and ``vfs`` before handing the policy to
    :func:`run_agentic_turn`. Without this gate the planner has
    historically picked "ask a clarifying question" over "search the
    attached docs" for ambiguous queries, even when the answer was
    in the inlined corpus head excerpt.
    """
    captured = _patch_agentic_turn(monkeypatch)
    sid = _create_session(client, tools_enabled=True)

    # Narrow the session ceiling to a single group that's neither
    # `documents` nor `vfs`, so the assertions below test the WIDENING
    # behavior — not the default-policy passthrough.
    patch_r = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["web"], "denied_tools": []},
    )
    assert patch_r.status_code == 200, patch_r.text

    # Attach a tiny valid PDF so the chat router computes a non-empty
    # `corpus_headlines` string before calling run_agentic_turn.
    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        b"xref\n0 3\n0000000000 65535 f\n0000000009 00000 n\n"
        b"0000000052 00000 n\ntrailer<</Size 3/Root 1 0 R>>\n"
        b"startxref\n96\n%%EOF\n"
    )
    upload_r = client.post(
        f"/v1/chat/sessions/{sid}/files",
        files={"file": ("course-descriptions.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_r.status_code == 201, upload_r.text

    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={"message": "who's teaching 800?"},
    )
    assert r.status_code == 200

    from kaos_agents.types.session_policy import SessionPolicy

    policy = captured["policy"]
    assert isinstance(policy, SessionPolicy)
    # The router must have FORCED these in even though the user
    # narrowed the ceiling to just `web`.
    assert "documents" in policy.allowed_groups, (
        f"documents missing from allowed_groups: {sorted(policy.allowed_groups)}"
    )
    assert "vfs" in policy.allowed_groups, (
        f"vfs missing from allowed_groups: {sorted(policy.allowed_groups)}"
    )
    # Soft ceiling raised in lockstep so auto-elevation can keep them.
    assert "documents" in policy.soft_ceiling
    assert "vfs" in policy.soft_ceiling
    # corpus_headlines must be non-empty (sanity check on the precondition).
    assert captured["corpus_headlines"]
    assert "course-descriptions.pdf" in captured["corpus_headlines"]
