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
from kaos_ui.agents import NO_TOOLS_PATTERN, augment_instructions

from app.logging_setup import app_logger
from app.models import SessionMeta, SessionToolSetWire

logger = app_logger("stream_proxy")


def _bearer_from_env() -> str:
    """Fallback bearer when a request didn't carry one.

    Production deploys set ``KAOS_AGENTS_API_API_TOKEN``. The
    double-API_ is the real env var name — see docs/PATTERNS.md P-001.
    """
    return os.environ.get("KAOS_AGENTS_API_API_TOKEN", "")


def _effective_tool_set(
    meta: SessionMeta, override: SessionToolSetWire | None
) -> SessionToolSetWire:
    """Return the tool-set the proxy should enforce for this turn.

    When ``override`` is non-None (set by the AgenticLoop's per-iteration
    worker adapter), use it. Otherwise fall back to ``meta.tool_set``
    (the legacy ceiling computed_field, derived from
    ``meta.policy.allowed_groups`` + ``meta.policy.denied_tools``).
    """
    return override if override is not None else meta.tool_set


def _tool_patterns(
    meta: SessionMeta,
    available_tool_names: Sequence[str] | None = None,
    tool_set_override: SessionToolSetWire | None = None,
) -> list[str]:
    """Resolve SessionMeta.tool_set into the explicit list of tool names
    the agent may invoke for this turn.

    Replaces the original fnmatch-glob path (FIX-14 wrap-up / TR-2). The
    SessionToolSet ceiling on the session decides which tool *groups*
    are reachable; we then expand each group via
    :func:`kaos_agents.context.filter_tools` so the actual contract
    matches the runtime catalog. Empty allowed_groups → no tools (the
    sentinel pattern, kept for the 0.1.0a1 empty-list-bug workaround).

    The hard read-only floor (the previous ``READ_ONLY_TOOL_GLOBS``
    list) now lives in :class:`SessionToolSetWire.denied_tools` — set
    once at session creation by the app's policy and never user-
    toggleable, so a future write tool can't slip in even when the
    user enables every group.

    When ``available_tool_names`` is omitted, we still send the group
    globs as a fallback so kaos-agents' fnmatch can apply them server-
    side. With the names list the proxy filters precisely against the
    same SessionToolSet contract the UI exposes.
    """
    tool_set = _effective_tool_set(meta, tool_set_override)
    if tool_set.is_blocking_all:
        return [NO_TOOLS_PATTERN]

    # No runtime visibility into the catalog → degrade to group-prefix
    # globs. Imperfect (won't enforce denied_tools at this layer) but
    # the bridge enforces fnmatch upstream so security is preserved.
    if not available_tool_names:
        return _group_globs(tool_set.allowed_groups)

    # Build a tool-name list via kaos-agents' filter_tools using the
    # SessionToolSet shape. Tools whose name doesn't appear in the
    # available list are silently dropped (catalog drift).
    try:
        from kaos_agents.context.tool_filter import filter_tools
        from kaos_agents.registry import default_tool_group_registry
        from kaos_agents.types.session_tool_set import SessionToolSet
    except ImportError:
        logger.warning("kaos_agents.context.tool_filter not importable; falling back to globs")
        return _group_globs(meta.tool_set.allowed_groups)

    session_tool_set = SessionToolSet(
        allowed_groups=frozenset(tool_set.allowed_groups),
        denied_tools=frozenset(tool_set.denied_tools),
    )

    # filter_tools works on tool *objects* (with .metadata.name / .name)
    # so wrap each available name in a tiny shim with the expected shape.
    class _NameOnly:
        __slots__ = ("name",)

        def __init__(self, name: str) -> None:
            self.name = name

    wrapped = [_NameOnly(n) for n in available_tool_names]
    kept = filter_tools(wrapped, session_tool_set, group_registry=default_tool_group_registry)
    kept_names = [t.name for t in kept]
    if not kept_names:
        # No tool in the catalog matches the ceiling — surface the
        # sentinel so the agent gets a deterministic "no tools" turn.
        return [NO_TOOLS_PATTERN]
    return kept_names


# Prefix → glob fallback when we have no runtime catalog handle. Keeps
# the broad "enable group X" contract working even when the proxy
# can't enumerate the catalog (eg. unit tests with a stub runtime).
_GROUP_GLOBS: dict[str, tuple[str, ...]] = {
    "web": ("kaos-source-*",),
    "documents": ("kaos-pdf-*", "kaos-office-parse-*", "kaos-content-*"),
    "citations": ("kaos-citations-*",),
    "vfs": ("kaos-core-vfs-*", "kaos-core-artifacts-*"),
}


def _group_globs(allowed_groups: Sequence[str]) -> list[str]:
    """Return the glob list that approximates an ``allowed_groups`` set.

    Fallback path when the proxy can't see the runtime catalog. Keeps
    the user-visible contract working even though it can't enforce
    ``denied_tools`` at this layer (the bridge does fnmatch enforcement
    upstream).
    """
    out: list[str] = []
    for group in allowed_groups:
        out.extend(_GROUP_GLOBS.get(group, ()))
    return out or [NO_TOOLS_PATTERN]


def _instructions_with_corpus(
    meta: SessionMeta,
    available_tool_names: Sequence[str] | None,
    corpus_markdown: str,
) -> str:
    """Compose the per-turn system prompt: base + tool catalog + corpus block.

    Tool catalog comes from kaos_ui.agents.augment_instructions. When
    ``corpus_markdown`` is non-empty, we append a "Documents attached"
    section after the catalog so the agent sees the file contents
    directly (P2-2: inline corpus because kaos-agents 0.1.0a1's
    MessageRequest has no per-turn corpus= field).
    """
    base = augment_instructions(
        base_prompt=meta.system_prompt,
        tools_enabled=meta.tools_enabled,
        available_tool_names=available_tool_names,
    )
    if not corpus_markdown:
        return base
    # Catalog of attached files — METADATA ONLY (filename, size,
    # content_type, VFS paths, summary). File bodies are not inlined;
    # the agent reads them via `kaos-content-*` / `kaos-pdf-*` tools
    # using the VFS paths in this block.
    #
    # The "search-before-clarify" behavior rule that used to live
    # here was deleted as part of the thin-worker-prompt refactor —
    # that's the GoalChecker's job (returns `needs_more_work` when
    # the agent says "I can't / I don't know" while tools are
    # available). See kaos-modules/docs/plans/thin-worker-prompt.md.
    return f"{base}\n\n## Documents attached to this session\n\n{corpus_markdown}"


def _build_forward_body(
    meta: SessionMeta,
    message: str,
    max_cost_usd: float,
    *,
    available_tool_names: Sequence[str] | None = None,
    corpus_markdown: str = "",
    tool_set_override: SessionToolSetWire | None = None,
) -> dict[str, Any]:
    return {
        "message": message,
        "model": meta.model,
        "instructions": _instructions_with_corpus(meta, available_tool_names, corpus_markdown),
        "tools": _tool_patterns(meta, available_tool_names, tool_set_override),
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
    corpus_markdown: str = "",
    tool_set_override: SessionToolSetWire | None = None,
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
        corpus_markdown=corpus_markdown,
        tool_set_override=tool_set_override,
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
