"""Helpers for kaos-agents-on-FastAPI apps.

Promotes the workarounds the `single-user-chat` example carried into
reusable helpers, so every kaos-agents-on-FastAPI app doesn't have to
re-invent them.

The workarounds compensate for two known kaos-agents 0.1.0a1
defaults that bit us during the chat-app build:

- ``create_app(runtime=None)`` defaults to an **in-memory** VFS (silent
  data loss across restarts) — :func:`build_chat_runtime` returns a
  disk-backed ``KaosRuntime`` so the caller's ``create_agent_app(runtime=...)``
  always persists.
- ``Runner`` skips creating a ``KaosContext`` when ``corpus`` is None,
  so bridged tools fail at execution with "No runtime context."
  :func:`install_tool_bridge_runtime_patch` idempotently patches
  ``kaos_agents.actions.tool_bridge.bridge_runtime_tools`` to thread
  ``KaosContext.create(runtime=runtime)`` when one isn't supplied.

:func:`augment_instructions` prepends the date preamble (Claude-class
models confidently hallucinate the year otherwise) and a
tools-disabled directive when applicable. It no longer inlines a
tool catalog — kaos-agents 0.1.0a5+ routes bridged tools through
kaos-llm-core's ReAct, which passes them to the LLM via the
provider's native tool-use API (``tools=``), so the catalog reaches
the model regardless of whether it appears in the system prompt.
See ``kaos-modules/docs/plans/thin-worker-prompt.md`` §4.5 (M5)
for the verification trail.

See `examples/single-user-chat/docs/UPSTREAM-NOTES.md` for the matching
upstream tickets.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from kaos_core import KaosRuntime
from kaos_core.logging import get_logger
from kaos_core.vfs import VFSConfig, VirtualFileSystem
from kaos_core.vfs.models import IsolationMode

logger = get_logger("kaos.ui.agents")

NO_TOOLS_PATTERN = "__kaos_ui_no_tools_match__"
"""Tool glob that matches nothing. Forward this in
``MessageRequest.tools`` when the caller wants 'no tools this turn'
without relying on the (currently buggy) empty-list semantics in
kaos-agents 0.1.0a1."""


# ── disk runtime ────────────────────────────────────────────────────


def build_chat_runtime(
    *,
    vfs_path: Path,
    register_extras: bool = True,
    install_bridge_patch: bool = True,
) -> tuple[KaosRuntime, tuple[str, ...]]:
    """Return a (runtime, tool_names) pair ready for ``create_agent_app``.

    Args:
        vfs_path: Where SessionMemory + our metadata sidecar live. The
            same path is shared with kaos-agents' SessionStore.
        register_extras: When True, also register ``kaos-pdf`` /
            ``kaos-office`` / ``kaos-content`` read tool surfaces if
            those packages are installed. Each registration is wrapped
            in ``contextlib.suppress(ImportError)`` so a slim deployment
            still works.
        install_bridge_patch: When True, monkey-patch
            ``bridge_runtime_tools`` to auto-construct a
            runtime-attached ``KaosContext`` if the Runner didn't. The
            patch is idempotent. Pass False if a future kaos-agents
            release fixes the underlying gap.

    Returns:
        ``(runtime, tool_names)``. ``runtime`` is a disk-backed
        ``KaosRuntime`` ready to pass to ``create_agent_app(runtime=...)``.
        ``tool_names`` is the sorted tuple of all registered tool names —
        used by callers to compose tool-pattern globs for
        ``MessageRequest.tools`` and by :func:`register_kaos_tool_groups`
        for the SessionToolSet partition.
    """
    if install_bridge_patch:
        install_tool_bridge_runtime_patch()

    vfs = VirtualFileSystem(
        config=VFSConfig(
            disk_base_path=vfs_path,
            isolation_mode=IsolationMode.GLOBAL,
        ),
    )
    runtime = KaosRuntime(vfs=vfs)

    total = 0
    with contextlib.suppress(ImportError):
        from kaos_core.tools import register_core_tools

        total += register_core_tools(runtime)

    if register_extras:
        # All optional kaos-* tool modules. kaos-ui doesn't declare
        # them as deps; consuming apps install whichever they want.
        # ImportError is suppressed so a slim deployment still works.
        with contextlib.suppress(ImportError):
            from kaos_pdf import register_pdf_tools  # ty: ignore[unresolved-import]

            total += register_pdf_tools(runtime)
        with contextlib.suppress(ImportError):
            from kaos_office import register_office_tools  # ty: ignore[unresolved-import]

            total += register_office_tools(runtime)
        with contextlib.suppress(ImportError):
            from kaos_content.tools import register_content_tools  # ty: ignore[unresolved-import]

            total += register_content_tools(runtime)
        # kaos-web — search, fetch, page-links, page-tables. Wires up
        # the search→load→links→navigate multi-step research loop.
        # Browser/crawl/domain tools come via register_web_all_tools.
        with contextlib.suppress(ImportError):
            from kaos_web import register_web_all_tools  # ty: ignore[unresolved-import]

            total += register_web_all_tools(runtime)
        # kaos-llm-core — typed LLM programs (Call, ReAct, RAG,
        # extraction) exposed as MCP tools. Lets the agent compose
        # smaller LLM calls inside a turn (e.g. corpus-filter, synthesize).
        with contextlib.suppress(ImportError):
            from kaos_llm_core.integrations.mcp.registration import (  # ty: ignore[unresolved-import]
                register_llm_core_tools,
            )

            total += register_llm_core_tools(runtime)
        # kaos-graph — RDF / SPARQL / graph algorithms.
        with contextlib.suppress(ImportError):
            from kaos_graph.tools import (  # ty: ignore[unresolved-import]
                register_graph_tools,
            )

            total += register_graph_tools(runtime)
        # kaos-agents — its own agent / memory / extraction / graph
        # MCP tools (kaos-agent-chat, kaos-agent-findings, etc).
        with contextlib.suppress(ImportError):
            from kaos_agents.tools.registry import (  # ty: ignore[unresolved-import]
                register_agent_tools,
            )

            total += register_agent_tools(runtime)

    logger.debug("registered %d tools on runtime", total)
    tool_names = tuple(sorted(runtime.tools.list_tools()))
    return runtime, tool_names


# ── upstream gap workaround ─────────────────────────────────────────


def install_tool_bridge_runtime_patch() -> None:
    """Idempotently patch ``bridge_runtime_tools`` to auto-create a
    runtime-attached ``KaosContext`` when one isn't supplied.

    Cause: ``kaos_agents.runtime.runner.Runner.__init__`` only builds a
    context when ``corpus is not None``. Without one, bridged tools
    receive ``context=None`` at execution time and fail with
    ``"No runtime context"``.

    Once kaos-agents fixes this upstream, callers can pass
    ``install_bridge_patch=False`` to :func:`build_chat_runtime` and
    delete this function from their codebase.
    """
    from kaos_agents.actions import tool_bridge  # ty: ignore[unresolved-import]
    from kaos_core.base.context import KaosContext

    if getattr(tool_bridge, "_kaos_ui_patched", False):
        return

    _original = tool_bridge.bridge_runtime_tools

    def patched(runtime: KaosRuntime, context: Any = None, **kwargs: Any) -> Any:
        if context is None:
            context = KaosContext.create(runtime=runtime)
        return _original(runtime, context, **kwargs)

    tool_bridge.bridge_runtime_tools = patched
    tool_bridge._kaos_ui_patched = True

    # Also patch the symbol that runner.py imported into its namespace.
    try:
        import kaos_agents.runtime.runner as runner_mod  # ty: ignore[unresolved-import]
    except ImportError:
        return
    if hasattr(runner_mod, "bridge_runtime_tools"):
        runner_mod.bridge_runtime_tools = patched


# ── system-prompt augmentation ──────────────────────────────────────


def _today_iso() -> str:
    """Return today's date as ISO-8601 (UTC). Pulled out so tests can patch."""
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()


def _date_preamble() -> str:
    """Top-of-prompt date marker.

    Claude / GPT / Gemini all default to their training-cutoff
    perception of "now" if no date is in context — which produces
    catastrophically confident hallucinations like "we are
    currently in 2024-2025; 2026 has not occurred yet." The model
    needs an explicit, unambiguous marker AT THE TOP of the
    system prompt, plus a directive to trust the marker over its
    training perception.
    """
    today = _today_iso()
    return (
        f"## TODAY IS {today}\n\n"
        f"The current date is **{today}**. Trust this date over any "
        "date you would otherwise infer from your training data. "
        "Your training cutoff is in the past; the user is asking "
        f"about the present, which is {today}. Never tell the user "
        '"that year has not occurred yet" or "we are currently in '
        '<some earlier year>" unless your evidence contradicts the '
        "date above — and your evidence had better be a tool result, "
        "not your training-data prior.\n\n"
    )


def augment_instructions(
    *,
    base_prompt: str,
    tools_enabled: bool,
) -> str:
    """Build the ``MessageRequest.instructions`` string for a turn.

    Composition: ``_date_preamble()`` + ``base_prompt`` + (when tools
    are disabled) a single refusal directive. The tool catalog is NOT
    inlined here — kaos-agents 0.1.0a5+ routes bridged tools through
    kaos-llm-core's ReAct, which hands them to the LLM via the
    provider's native tool-use API (``tools=``). The model sees tool
    names and descriptions in the wire payload regardless of whether
    they appear in the system prompt, so inlining a catalog block is
    redundant overhead.

    Worker prompt = date + voice. Behavior policy (which tools to
    use, when to search, when to escalate) lives in the kaos-agents
    Signature decision points — ``_TurnToolPolicySignature`` docstring
    picks ``kept_groups``, ``_GoalCheckerSignature`` docstring drives
    replan verdicts, and the AgenticLoop threads the critic's
    ``next_action`` to the next worker iteration as ``thinking_note``.
    Free-text rules in this prompt would (a) duplicate, (b) drift
    from, and (c) potentially contradict those Signatures.

    See ``kaos-modules/docs/plans/thin-worker-prompt.md`` for the full
    rationale + the anti-goals checklist that blocks regrowing this
    function with hardcoded English behavior rules.

    Args:
        base_prompt: The user-facing system prompt from session
            metadata.
        tools_enabled: Whether tools should be available this turn.

    Returns:
        A composed system prompt ready to thread into
        ``MessageRequest.instructions``.
    """
    preamble = _date_preamble()
    if not tools_enabled:
        return (
            f"{preamble}{base_prompt}\n\n"
            "Tools are disabled for this session. You cannot call KAOS tools "
            "in this turn, and if the user asks what tools you can use, say "
            "that no KAOS tools are enabled for this session."
        )
    return f"{preamble}{base_prompt}"


# ── tool-group registration ────────────────────────────────────────


# Prefix → group-name map. Evaluated in order; longer prefixes first so
# ``kaos-core-vfs-`` matches before ``kaos-core-``. Tools that don't
# match any prefix simply aren't grouped — they pass through any
# ``SessionToolSet`` that has no ``allowed_groups`` set, but are
# blocked when an allow-list is set. That's the desired UX: groups
# are an opt-in narrowing layer over the unrestricted default.
KAOS_TOOL_GROUP_PREFIXES: tuple[tuple[str, str], ...] = (
    # kaos-web tools sit under "web" (the canonical general-web group).
    # Longest-prefix-wins ordering: keep more specific prefixes above.
    ("kaos-web-browser-", "browser"),
    ("kaos-web-domain-", "netinfra"),
    ("kaos-web-", "web"),
    ("kaos-source-", "sources"),
    ("kaos-pdf-", "documents"),
    ("kaos-office-parse-", "documents"),
    ("kaos-content-", "documents"),
    ("kaos-citations-", "citations"),
    ("kaos-core-vfs-", "vfs"),
    ("kaos-core-artifacts-", "vfs"),
    ("kaos-llm-core-", "llm"),
    ("kaos-graph-", "graph"),
    ("kaos-agent-", "agent"),
)

# Per-group descriptions — surfaced into ``GET /v1/chat/categories``
# and to the agent via the system prompt. Keep them short + LLM-
# parseable so a planner Program (TR-5) can route on them.
KAOS_TOOL_GROUP_DESCRIPTIONS: dict[str, str] = {
    "web": (
        "General web search and page fetch (SerpAPI / Brave / Exa "
        "search, HTTP fetch, page links, page tables, page metadata). "
        "Enable for any question that needs live web content — "
        "current officeholders, current events, public webpages."
    ),
    "browser": (
        "JS-rendered web pages via Playwright. Enable when an httpx "
        "fetch returns no useful HTML (modern SPAs, candidate lists, "
        "interactive dashboards)."
    ),
    "netinfra": (
        "DNS / WHOIS / TLS / TCP / HTTP-header introspection. Enable "
        "for forensic / infrastructure / cybersecurity questions."
    ),
    "sources": (
        "Regulatory + legal data sources (Federal Register, eCFR, "
        "EDGAR, GovInfo, PACER, GLEIF). Enable for research about "
        "regulations, SEC filings, court dockets, or entity identifiers."
    ),
    "documents": (
        "Parse uploaded PDF / DOCX / PPTX / XLSX files and search "
        "their content. Enable when the user has uploaded files and "
        "may ask about them."
    ),
    "citations": (
        "Extract typed Bluebook / financial / accounting citations "
        "from text. Enable for legal or financial analysis work."
    ),
    "vfs": (
        "Browse and read files from the session's virtual filesystem. "
        "Enable when the agent needs to confirm what's been uploaded "
        "or read raw bytes alongside the parsed AST."
    ),
    "llm": (
        "Typed LLM-program tools (Call / ReAct / RAG / extraction). "
        "Enable for compose-able sub-LLM tasks inside a turn."
    ),
    "graph": (
        "Session knowledge-graph access (SPARQL, walk, projections). "
        "Enable when reasoning over the run's accumulated PROV-O graph."
    ),
    "agent": (
        "Agent-introspection tools (memory query/search, recipe list, "
        "findings/corpus-filter). Enable for meta-agent workflows."
    ),
}


def register_kaos_tool_groups(runtime: KaosRuntime) -> dict[str, int]:
    """Partition runtime-registered tools into kaos-agents tool groups.

    Discovers every tool currently registered on ``runtime`` (via
    :func:`runtime.tools.list_tools`) and groups them by the prefix
    map in :data:`KAOS_TOOL_GROUP_PREFIXES`. Each non-empty group is
    registered (idempotent — uses ``force=True``) into
    :data:`kaos_agents.registry.default_tool_group_registry` so that
    :class:`SessionToolSet` + :func:`filter_tools` can narrow the
    catalog per-session.

    Call AFTER every tool-registration call has run (i.e. after
    :func:`build_chat_runtime` AND after any caller-specific
    ``register_<x>_tools`` invocations). Re-runs are safe — the
    registry replaces existing entries with the same name.

    Args:
        runtime: The :class:`KaosRuntime` whose tool catalog should be
            partitioned.

    Returns:
        ``{group_name: tool_count}`` for the groups that ended up with
        at least one tool. Empty groups are omitted. Useful for log /
        telemetry purposes when the caller wants to confirm the
        partition matched what they expected.
    """
    try:
        from kaos_agents.registry import (  # ty: ignore[unresolved-import]
            default_tool_group_registry,
        )
        from kaos_agents.types import ToolGroup  # ty: ignore[unresolved-import]
    except ImportError:
        # kaos-agents not installed — caller is using kaos_ui.agents for
        # other helpers (eg. build_chat_runtime) but doesn't want the
        # ChatAgent surface. No-op.
        logger.debug("kaos_agents not importable; skipping tool-group registration")
        return {}

    tool_names = list(runtime.tools.list_tools())
    by_group: dict[str, list[str]] = {g: [] for g in KAOS_TOOL_GROUP_DESCRIPTIONS}
    for name in tool_names:
        for prefix, group in KAOS_TOOL_GROUP_PREFIXES:
            if name.startswith(prefix):
                by_group[group].append(name)
                break

    counts: dict[str, int] = {}
    for group_name, group_tools in by_group.items():
        if not group_tools:
            continue
        default_tool_group_registry.register(
            ToolGroup(
                name=group_name,
                description=KAOS_TOOL_GROUP_DESCRIPTIONS[group_name],
                tool_names=tuple(sorted(group_tools)),
            ),
            force=True,
        )
        counts[group_name] = len(group_tools)
    logger.debug(
        "registered %d kaos tool groups: %s",
        len(counts),
        ", ".join(f"{g}={n}" for g, n in counts.items()),
    )
    return counts


__all__ = [
    "KAOS_TOOL_GROUP_DESCRIPTIONS",
    "KAOS_TOOL_GROUP_PREFIXES",
    "NO_TOOLS_PATTERN",
    "augment_instructions",
    "build_chat_runtime",
    "install_tool_bridge_runtime_patch",
    "register_kaos_tool_groups",
]
