"""Helpers for kaos-agents-on-FastAPI apps.

Promotes the workarounds the `single-user-chat` example carried into
reusable helpers, so every kaos-agents-on-FastAPI app doesn't have to
re-invent them.

The workarounds compensate for three known kaos-agents 0.1.0a1
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
- The agent isn't told which tools it can call. :func:`augment_instructions`
  takes a session's base system prompt + a tool-name catalog and
  returns the prompt the agent should actually see, so the model
  doesn't have to discover its toolset by trial-and-error.

See `examples/single-user-chat/docs/UPSTREAM-NOTES.md` for the matching
upstream tickets.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
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
        callers thread it into :func:`augment_instructions` so the
        agent knows what it can call.
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
        # kaos-pdf / kaos-office / kaos-content are runtime-optional.
        # kaos-ui doesn't declare them as deps; consuming apps install
        # whichever they want. ImportError is suppressed at runtime
        # when absent.
        with contextlib.suppress(ImportError):
            from kaos_pdf import register_pdf_tools  # ty: ignore[unresolved-import]

            total += register_pdf_tools(runtime)
        with contextlib.suppress(ImportError):
            from kaos_office import register_office_tools  # ty: ignore[unresolved-import]

            total += register_office_tools(runtime)
        with contextlib.suppress(ImportError):
            from kaos_content.tools import register_content_tools

            total += register_content_tools(runtime)

    logger.info("registered %d tools on runtime", total)
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


def augment_instructions(
    *,
    base_prompt: str,
    tools_enabled: bool,
    available_tool_names: Sequence[str] | None = None,
) -> str:
    """Build the ``MessageRequest.instructions`` string for a turn.

    kaos-agents 0.1.0a1 doesn't inject the tool catalog into the
    system prompt automatically. Without that, the LLM denies having
    tools even when they're properly bridged. We patch around it by
    prepending the catalog ourselves.

    Args:
        base_prompt: The user-facing system prompt from session
            metadata.
        tools_enabled: Whether tools should be available this turn.
        available_tool_names: Names of tools that will be bridged
            (must match what the proxy sends in ``tools``). Ignored
            when ``tools_enabled`` is False.

    Returns:
        A composed system prompt ready to thread into
        ``MessageRequest.instructions``.
    """
    if not tools_enabled:
        return (
            f"{base_prompt}\n\n"
            "Tools are disabled for this session. You cannot call KAOS tools "
            "in this turn, and if the user asks what tools you can use, say "
            "that no KAOS tools are enabled for this session."
        )

    tool_names = sorted({name for name in available_tool_names or () if name})
    if not tool_names:
        return (
            f"{base_prompt}\n\n"
            "Tools are enabled for this session, but the backend did not "
            "register any KAOS tools."
        )

    catalog = "\n".join(f"- {name}" for name in tool_names)
    return (
        f"{base_prompt}\n\n"
        f"Tools are enabled for this session. Available KAOS tool names "
        f"({len(tool_names)}):\n{catalog}\n\n"
        "When the user asks what tools you can use, answer from this list."
    )


__all__ = [
    "NO_TOOLS_PATTERN",
    "augment_instructions",
    "build_chat_runtime",
    "install_tool_bridge_runtime_patch",
]
