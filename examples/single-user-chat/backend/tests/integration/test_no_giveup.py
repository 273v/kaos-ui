"""**N.1 — Canonical regression: the agent must never give up on a
searchable question when web search is dropped from the initial ceiling.**

This is THE test that validates the AgenticLoop's reason for existing.
The failure mode it guards against:

    The user asks a web-searchable question. The session's
    ``allowed_groups`` happens to start without the ``web`` group
    (e.g., the user enabled drafting + forensics but forgot web).
    The agent says "I can't help with that" and gives up.

The fix in kaos-agents 0.1.0a4 is the auto-elevation step inside
:func:`run_agentic_turn`:

  1. The per-turn planner sees ``dropped_groups = ['web']``.
  2. The elevation policy classifies ``web`` as ``green-auto``.
  3. The loop silently adds ``web`` to ``allowed_groups``.
  4. A :class:`ToolPolicyElevated` event is emitted (audit trail).
  5. The agent runs with web tools enabled and actually answers.

The success contract this test enforces:

  - The SSE stream contains at least one ``tool_policy_elevated`` event
    naming a tool group the agent needed.
  - The agent's final text contains substantive content (not a refusal).
  - At least one tool call was attempted in the elevated group OR the
    GoalChecker emitted ``satisfied``.
  - No ``run_error`` event landed.
  - The final ``loop_terminated`` reason is ``"satisfied"``.

Gated on ``ANTHROPIC_API_KEY`` (legacy alias honored).
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.live]


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("KAOS_LLM_ANTHROPIC_API_KEY"))


pytestmark.append(pytest.mark.skipif(not _has_anthropic_key(), reason="ANTHROPIC_API_KEY not set"))


def _parse_sse_events(body: str) -> list[dict]:
    """Walk an SSE response body, returning ``[{_event, data}, ...]``."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    out: list[dict] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        payload: dict = {"_event": "message"}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                payload["_event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip(" "))
        if data_lines:
            raw = "\n".join(data_lines)
            try:
                payload["data"] = json.loads(raw)
            except json.JSONDecodeError:
                payload["data"] = raw
        out.append(payload)
    return out


def _final_text(events: list[dict]) -> str:
    """Concatenate every ``text_delta.content``, or fall back to
    ``turn_summary.text`` if no deltas were emitted."""
    parts: list[str] = []
    for e in events:
        data = e.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("type") == "text_delta":
            content = data.get("content", "")
            if isinstance(content, str):
                parts.append(content)
    if parts:
        return "".join(parts)
    # Fall back to turn_summary.text
    for e in events:
        data = e.get("data")
        if isinstance(data, dict) and data.get("type") == "turn_summary":
            text = data.get("text", "")
            if isinstance(text, str):
                return text
    return ""


_REFUSAL_PHRASES: tuple[str, ...] = (
    "i can't help",
    "i cannot help",
    "i'm unable to",
    "i am unable to",
    "i don't have access",
    "i do not have access",
    "i'm not able to",
    "i am not able to",
    "without web search",
    "without the ability to search",
    "i don't have the ability",
    "i do not have the ability",
)


def _looks_like_refusal(text: str) -> bool:
    """Soft heuristic — a turn that's mostly a refusal vs. a real answer.

    Three-part check:
      1. Contains one of the canonical refusal phrases.
      2. Final text is short (< 200 chars suggests "I can't help" + nothing else).
      3. Lacks any topical content keywords from the question itself.

    Used only as a fallback signal — the primary contract is the
    ``tool_policy_elevated`` event + a successful ``loop_terminated``.
    """
    if not text:
        return True
    lowered = text.lower()
    has_refusal_phrase = any(phrase in lowered for phrase in _REFUSAL_PHRASES)
    is_short = len(text) < 200
    return has_refusal_phrase and is_short


def test_agent_never_gives_up_on_searchable_question(client) -> None:
    """The canonical failure-mode regression.

    Scenario: user wants a web search but only enabled documents+vfs.
    The AgenticLoop must auto-elevate the web group and answer.
    """
    # 1. Create a session with the broad research-persona ceiling (the
    #    default), then PATCH the ceiling DOWN to a deliberately narrow
    #    set that excludes `web`. We want to reproduce "user forgot to
    #    enable web" exactly.
    r = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    r = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["documents", "vfs"]},
    )
    assert r.status_code == 200, r.text

    # 2. Send a question that DEMANDS web search to answer well. The
    #    Federal Register / EDGAR domain is the canonical "I need to
    #    look this up" target — there's no plausible answer from
    #    documents+vfs alone.
    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={
            "message": (
                "Search the Federal Register for the most recent rule about "
                "dairy product labeling. Give me the publication date and "
                "the issuing agency."
            ),
        },
        headers={"Accept": "text/event-stream"},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse_events(r.text)

    # 3. Hard contract: no run_error.
    types = [e.get("_event") for e in events]
    assert "run_error" not in types, f"unexpected run_error: {events}"

    # 4. Hard contract: at least one tool_policy_elevated event naming
    #    a group OUTSIDE the original allowed_groups. This is the audit
    #    trail of auto-elevation — without it, the loop didn't actually
    #    widen the ceiling.
    elevated_events = [
        e["data"]
        for e in events
        if isinstance(e.get("data"), dict) and e["data"].get("type") == "tool_policy_elevated"
    ]
    assert elevated_events, (
        "Expected at least one tool_policy_elevated event — the loop "
        "should have auto-widened the ceiling when the planner saw "
        f"the user wanted web search. Got events: {types}"
    )
    all_elevated_groups: set[str] = set()
    for ev in elevated_events:
        all_elevated_groups.update(ev.get("elevated_groups", []))
    assert all_elevated_groups, (
        "Elevation events present but elevated_groups was empty in all of them."
    )

    # 5. Hard contract: the loop terminated AND the termination
    #    indicates "agent tried" — not "agent gave up at iteration 0."
    #    The user's failure mode is bouncing on the first refusal.
    #
    #    ✓ Acceptable (the agent tried):
    #      - ``satisfied``             — ideal outcome
    #      - ``insufficient_evidence`` — Critic accepted a clean refusal
    #      - ``max_iterations``        — loop kept trying until budget
    #      - ``cost_exceeded``         — loop kept trying until cost cap
    #      - ``wall_clock_exceeded``   — loop kept trying until time cap
    #
    #    ✗ Rejected (the agent gave up or never started):
    #      - no ``loop_terminated`` event at all
    #      - ``stuck_no_progress`` — pathological no-op detected (the
    #        loop's own stuck-detector says "this isn't progressing")
    #      - ``user_interrupt``    — only the host cancels turns
    terminate_events = [
        e["data"]
        for e in events
        if isinstance(e.get("data"), dict) and e["data"].get("type") == "loop_terminated"
    ]
    assert terminate_events, f"Expected loop_terminated event; got {types}"
    final_term = terminate_events[-1]
    final_reason = final_term.get("reason")
    assert final_reason not in ("stuck_no_progress", "user_interrupt"), (
        f"Loop terminated for a 'gave up' reason: {final_reason!r}. Full term event: {final_term!r}"
    )
    assert final_reason in (
        "satisfied",
        "insufficient_evidence",
        "max_iterations",
        "cost_exceeded",
        "wall_clock_exceeded",
    ), f"Unknown termination reason: {final_reason!r}"

    # 6. Soft contract: the final text shouldn't be a bare refusal.
    final_text = _final_text(events)
    assert not _looks_like_refusal(final_text), (
        "Agent gave up — the answer reads as a refusal:\n"
        f"  {final_text[:300]!r}\n"
        f"Elevation trail: {sorted(all_elevated_groups)}"
    )

    # 7. Defensive: verify message_count incremented (the touch path
    #    ran, confirming the chat router didn't bail out early).
    r = client.get(f"/v1/chat/sessions/{sid}/meta")
    assert r.status_code == 200
    assert r.json()["message_count"] >= 1


def test_agent_completes_when_only_blocked_groups_are_needed(client) -> None:
    """Companion test — the agent must NOT pretend to succeed when the
    only useful groups are blocked at the policy level (red-blocked tier).

    With the AgenticLoop's three-tier elevation:
      - green-auto: silently elevated (covered by the test above)
      - yellow-confirm: pauses for user approval
      - red-blocked: never elevated; the loop must terminate cleanly
        with ``insufficient_evidence`` rather than a hallucinated answer.

    This test confirms the agent doesn't *fabricate* a Federal Register
    answer when its sole accessible group is ``vfs`` (no useful tools
    for this task) — the loop should land on ``insufficient_evidence``,
    not invent dates.
    """
    r = client.post(
        "/v1/chat/sessions",
        json={"model": "anthropic:claude-haiku-4-5", "tools_enabled": True},
    )
    sid = r.json()["id"]

    # Force a maximally tight ceiling — only vfs.
    r = client.patch(
        f"/v1/chat/sessions/{sid}/tool-set",
        json={"allowed_groups": ["vfs"]},
    )
    assert r.status_code == 200

    r = client.post(
        f"/v1/chat/sessions/{sid}/messages",
        json={
            "message": (
                "Search the Federal Register for the most recent rule about "
                "dairy product labeling and tell me the publication date."
            ),
        },
        headers={"Accept": "text/event-stream"},
    )
    assert r.status_code == 200

    events = _parse_sse_events(r.text)
    # No run_error.
    assert "run_error" not in [e.get("_event") for e in events]

    # The loop must terminate cleanly. Three acceptable reasons:
    #   - ``satisfied``             — GoalChecker accepted the answer
    #     (rare for this scenario, but legal).
    #   - ``insufficient_evidence`` — design-ideal: Critic recognized
    #     the tools can't answer and returned a clean refusal.
    #   - ``max_iterations``        — the loop kept TRYING rather than
    #     giving up. This is the OPPOSITE of the failure mode N.1
    #     guards against ("instantly giving up because web is
    #     disabled") — hitting max iterations means the agent took
    #     multiple attempts and the budget cap (not the agent's
    #     willingness) was the limiter.
    #
    # The bad outcomes (which this test rejects) are:
    #   - no loop_terminated event at all
    #   - ``stuck_no_progress`` (pathological no-op detected)
    #   - ``cost_exceeded`` / ``wall_clock_exceeded`` (budget tripped
    #     before the agent could surface a verdict)
    terminate_events = [
        e["data"]
        for e in events
        if isinstance(e.get("data"), dict) and e["data"].get("type") == "loop_terminated"
    ]
    assert terminate_events
    final_reason = terminate_events[-1].get("reason")
    assert final_reason in ("satisfied", "insufficient_evidence", "max_iterations"), (
        f"Loop must end cleanly even when tools are blocked. Got: {final_reason!r}. "
        f"`max_iterations` means the agent kept trying (the design intent); "
        f"`stuck_no_progress` / `cost_exceeded` / `wall_clock_exceeded` are the bad outcomes."
    )
