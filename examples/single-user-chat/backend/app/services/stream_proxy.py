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
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.logging_setup import app_logger
from app.models import SessionMeta

logger = app_logger("stream_proxy")


def _bearer_from_env() -> str:
    """Fallback bearer when a request didn't carry one.

    Production deploys set ``KAOS_AGENTS_API_API_TOKEN``. The
    double-API_ is the real env var name — see docs/PATTERNS.md P-001.
    """
    return os.environ.get("KAOS_AGENTS_API_API_TOKEN", "")


def _build_forward_body(meta: SessionMeta, message: str, max_cost_usd: float) -> dict[str, Any]:
    return {
        "message": message,
        "model": meta.model,
        "instructions": meta.system_prompt,
        "tools": ["*"] if meta.tools_enabled else [],
        "max_cost_usd": max_cost_usd,
    }


async def stream_chat(
    *,
    client: httpx.AsyncClient,
    bearer_token: str,
    meta: SessionMeta,
    message: str,
    max_cost_usd: float,
) -> AsyncIterator[dict[str, str]]:
    """Yield `{event, data}` records ready for `sse_starlette`.

    Each iteration corresponds to one SSE event from kaos-agents.
    Pure pass-through — the frontend dispatches on the 15 wire types
    per ARCHITECTURE.md § 5.3.
    """
    body = _build_forward_body(meta, message, max_cost_usd)
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }

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

        event_name = "message"
        async for raw_line in response.aiter_lines():
            if raw_line == "":
                continue
            if raw_line.startswith("event: "):
                event_name = raw_line[len("event: ") :].strip()
            elif raw_line.startswith("data: "):
                data = raw_line[len("data: ") :]
                yield {"event": event_name, "data": data}
            # other prefixes (id:, retry:, comments) ignored
