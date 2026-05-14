"""SSE proxy to the kaos-agents bundled API.

We POST to `/v1/sessions/{id}/messages` (in-process via httpx
ASGITransport — see main.py) with our metadata applied as per-turn
overrides (`model`, `instructions`, `tools`, `max_cost_usd`) and
re-stream the SSE events back to our caller.

Verified shapes — `MessageRequest` field is `instructions`, NOT
`system_prompt`. See docs/PATTERNS.md P-005.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.logging_setup import app_logger
from app.models import SessionMeta

logger = app_logger("stream_proxy")

_NO_TOOLS_PATTERN = "__kaos_chat_example_no_tools__"


def _bearer_from_env() -> str:
    """Fallback bearer when a request didn't carry one.

    Production deploys set ``KAOS_AGENTS_API_API_TOKEN``. The
    double-API_ is the real env var name — see docs/PATTERNS.md P-001.
    """
    return os.environ.get("KAOS_AGENTS_API_API_TOKEN", "")


def _tool_patterns(meta: SessionMeta) -> list[str]:
    """Translate the example-app toggle to kaos-agents glob semantics.

    In kaos-agents 0.1.0a1 an empty tools list means "no explicit filter",
    which bridges every runtime tool. Use a deliberately unmatched glob for
    disabled sessions so the UI toggle is a real execution gate.

    When enabled, only the curated read-only allowlist is exposed.
    The UI label says "Enable read-only tools" — this keeps that
    promise even if a future kaos module adds write tools.
    """
    if meta.tools_enabled:
        from app.services.catalog import READ_ONLY_TOOL_GLOBS

        return list(READ_ONLY_TOOL_GLOBS)
    return [_NO_TOOLS_PATTERN]


def _instructions_with_tool_state(
    meta: SessionMeta,
    available_tool_names: Sequence[str] | None,
) -> str:
    if not meta.tools_enabled:
        return (
            f"{meta.system_prompt}\n\n"
            "Tools are disabled for this session. You cannot call KAOS tools in this "
            "turn, and if the user asks what tools you can use, say that no KAOS "
            "tools are enabled for this session."
        )

    tool_names = sorted({name for name in available_tool_names or () if name})
    if not tool_names:
        return (
            f"{meta.system_prompt}\n\n"
            "Tools are enabled for this session, but the backend did not register any "
            "KAOS tools."
        )

    catalog = "\n".join(f"- {name}" for name in tool_names)
    return (
        f"{meta.system_prompt}\n\n"
        f"Tools are enabled for this session. Available KAOS tool names "
        f"({len(tool_names)}):\n{catalog}\n\n"
        "When the user asks what tools you can use, answer from this list."
    )


def _build_forward_body(
    meta: SessionMeta,
    message: str,
    max_cost_usd: float,
    *,
    available_tool_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "message": message,
        "model": meta.model,
        "instructions": _instructions_with_tool_state(meta, available_tool_names),
        "tools": _tool_patterns(meta),
        "max_cost_usd": max_cost_usd,
    }


async def stream_chat(
    *,
    client: httpx.AsyncClient,
    bearer_token: str,
    meta: SessionMeta,
    message: str,
    max_cost_usd: float,
    available_tool_names: Sequence[str] | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Yield `{event, data}` records ready for `sse_starlette`.

    Each iteration corresponds to one SSE event from kaos-agents.
    Pure pass-through — the frontend dispatches on the 15 wire types
    per ARCHITECTURE.md § 5.3.
    """
    body = _build_forward_body(
        meta,
        message,
        max_cost_usd,
        available_tool_names=available_tool_names,
    )
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }

    # Reuse `kaos_llm_client.transport.parse_sse_stream` rather than
    # hand-rolling a line parser. It already handles:
    #   * multi-line `data:` accumulation
    #   * blank-line dispatch boundaries
    #   * `[DONE]` sentinel termination
    #   * wall-clock max-duration enforcement
    #   * CRLF/LF normalization
    # The kaos-agents wire format puts the event-type discriminator
    # inside the JSON payload as `type`, so we don't need the SSE
    # `event:` field for routing — we recover it from `data["type"]`
    # and forward both for sse-starlette compatibility.
    from kaos_llm_client.transport import parse_sse_stream

    async with client.stream(
        "POST",
        f"/v1/sessions/{meta.id}/messages",
        headers=headers,
        json=body,
    ) as response:
        if response.status_code >= 400:
            err = await response.aread()
            logger.warning("upstream %s for session=%s", response.status_code, meta.id)
            yield {
                "event": "run_error",
                "data": json.dumps(
                    {
                        "type": "run_error",
                        "what": f"Upstream kaos-agents returned {response.status_code}",
                        "how_to_fix": (
                            "Check backend logs and KAOS_AGENTS_API_API_TOKEN. "
                            f"Body: {err.decode('utf-8', errors='replace')[:300]}"
                        ),
                    }
                ),
            }
            return

        async for payload in parse_sse_stream(response):
            # `payload` is the already-decoded `data:` JSON dict. Use
            # its `type` field for the SSE event-name; re-encode as
            # JSON for sse-starlette's wire format. Default to
            # "message" (SSE spec default) for shape-malformed events.
            event_name = (payload.get("type") if isinstance(payload, dict) else None) or "message"
            yield {"event": event_name, "data": json.dumps(payload)}
