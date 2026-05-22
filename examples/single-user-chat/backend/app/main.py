"""Single-User Chat backend entrypoint.

Mounts `kaos_agents.api.server.create_app()` and layers our extension
routers on top:

    /v1/health           ← our health router
    /v1/models           ← our model catalog
    /v1/chat/*           ← our session sidecar + chat proxy

    /v1/sessions/*       ← kaos-agents (mounted by create_app)
    /v1/runs/*/approve   ← kaos-agents
    /openapi.json /docs  ← kaos-agents

The disk-backed runtime, the kaos-agents `bridge_runtime_tools` patch,
and the optional kaos-pdf / kaos-office / kaos-content tool surface
are all delegated to `kaos_ui.agents.build_chat_runtime`, which is the
canonical home for these "kaos-agents 0.1.0a1 on FastAPI" workarounds.
See `kaos-ui` README and the upstream issues filed on 273v/kaos-agents
(#16 fixed in kaos-agents main, #17 + #18 pending design review) — once
those land, the workarounds inside `kaos_ui.agents` will simplify in
the next kaos-ui release.
"""

from __future__ import annotations

import contextlib

import httpx
from kaos_agents.api.server import create_app as create_agent_app

# ---------------------------------------------------------------------------
# URI contract redesign (kaos-core 0.1.0a10) — Stage 3 wiring.
# The SPA uploads files into ``sessions/<sid>/files/<name>``. The 0.1.0a10
# resolver routes bare-name tool inputs through ``context.default_vfs_namespace``,
# so every KaosContext built downstream by kaos-agents must carry "files/" for
# the agent's bare-name lookups to land. kaos-agents 0.1.0a14 doesn't yet
# construct a per-session KaosContext with the host's namespace (will ship in
# 0.1.0a15+); until then we patch ``KaosContext.__init__`` to default the
# namespace to "files/" when the caller doesn't supply one. Idempotent.
# ---------------------------------------------------------------------------
# kaos-agents Runner only builds a KaosContext when ``corpus`` is set; for
# normal chat turns it passes ``context=None`` to ``bridge_runtime_tools``,
# which means tools fall back to a runtime-less stub context with no VFS.
# Patch the internal-agent builder to materialise a real session-scoped
# context with ``default_vfs_namespace`` set to the SPA upload prefix so
# file-input tools resolve bare names like ``"EMNA Mutual NDA.docx"`` to
# the on-disk session VFS at ``sessions/<sid>/files/<name>``.
#
# Because the SPA runtime VFS uses GLOBAL isolation (see
# build_chat_runtime), context_id is NOT prepended automatically — the
# session prefix has to be in the namespace string itself.
#
# Will be obsolete once kaos-agents 0.1.0a15 builds the per-session
# context natively + the SPA backend switches to PER_CONTEXT isolation.
from kaos_agents.runtime.runner import Runner as _Runner
from kaos_core.base.context import KaosContext as _KaosContext
from kaos_ui.agents import build_chat_runtime

from app.logging_setup import app_logger, configure
from app.persistence.sessions import SessionStore
from app.routers import (
    chat,
    citations,
    feedback,
    files,
    health,
    messages,
    models,
    replay,
    runs,
)
from app.settings import AppSettings

if not getattr(_Runner, "_spa_context_injection_patch_applied", False):
    _original_build_internal = _Runner._build_internal_agent

    def _patched_build_internal(self, session_id, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Always construct a fresh per-session context so the namespace
        # tracks the request's session_id. SPA uploads land at
        # ``sessions/<sid>/files/<name>`` on disk (global-isolation VFS).
        if self._runtime is not None:
            namespace = f"sessions/{session_id}/files/"
            self._context = _KaosContext(
                session_id=session_id,
                runtime=self._runtime,
                vfs=self._runtime.vfs,
                default_vfs_namespace=namespace,
            )
        return _original_build_internal(self, session_id, *args, **kwargs)

    _Runner._build_internal_agent = _patched_build_internal  # ty: ignore[invalid-assignment]
    _Runner._spa_context_injection_patch_applied = True  # ty: ignore[unresolved-attribute]


# B0/#582 — kaos-core path_resolver double-prefix workaround.
# kaos-core 0.1.0's ``path_resolver._resolve`` non-idempotently
# prepends ``context.default_vfs_namespace`` to bare names (see
# ``path_resolver.py:406`` —
# ``vfs_lookup = namespace + stripped if namespace else stripped``).
# Our corpus catalog block in ``app/services/uploads.py:670`` advertises
# the fully-qualified VFS path to the LLM ("- VFS bytes: `sessions/{sid}/
# files/{name}`"); the model copies it into the tool call; the resolver
# then double-prefixes it to ``sessions/{sid}/files/sessions/{sid}/files/{name}``,
# which doesn't exist. Discovered via T6 in the broad-reliability Chrome
# MCP matrix; will be fixed cleanly in a kaos-core release. Strip the
# duplicate prefix at the public-entry preprocessing step here as the
# interim workaround.
import kaos_core.path_resolver as _kaos_core_path_resolver  # noqa: E402

if not getattr(
    _kaos_core_path_resolver, "_spa_double_prefix_workaround_applied", False
):
    _original_resolve_input_path = _kaos_core_path_resolver.resolve_input_path

    def _strip_duplicate_namespace_prefix(path_or_uri, context):  # type: ignore[no-untyped-def]
        """If ``path_or_uri`` already starts with the context's default
        namespace, return it with the leading copy stripped — so the
        downstream prepend produces a single prefix, not a double one.

        Idempotent. Safe for URIs (``file://``, ``artifact://``, ...) —
        those never start with the namespace and pass through unchanged.
        """
        if context is None or not isinstance(path_or_uri, str):
            return path_or_uri
        namespace = getattr(context, "default_vfs_namespace", "") or ""
        if not namespace:
            return path_or_uri
        # Match the resolver's own normalization (strip leading "/")
        stripped = path_or_uri.lstrip("/")
        if stripped.startswith(namespace):
            return stripped[len(namespace) :]
        return path_or_uri

    def _patched_resolve_input_path(
        path_or_uri,
        *,
        context=None,
        **kwargs,
    ):  # type: ignore[no-untyped-def]
        normalized = _strip_duplicate_namespace_prefix(path_or_uri, context)
        return _original_resolve_input_path(
            normalized, context=context, **kwargs
        )

    _kaos_core_path_resolver.resolve_input_path = _patched_resolve_input_path  # ty: ignore[invalid-assignment]
    _kaos_core_path_resolver._spa_double_prefix_workaround_applied = True  # ty: ignore[unresolved-attribute]


# #583 — Filter SPA sidecars from the agent-visible VFS listing.
# ``app/services/uploads.py`` writes two sidecars next to every
# uploaded file:
#   - ``<file>.kaos.json`` — parsed ContentDocument AST sidecar
#   - ``<file>.meta.json`` — FileMeta sidecar (size, parse status, etc.)
# Both live in the same ``sessions/{sid}/files/`` namespace as the
# original. When the agent calls ``kaos-core-vfs-list``, it sees ALL
# three entries per uploaded file and picks the sidecar instead of
# the original on retries — discovered via T6 in the broad-reliability
# Chrome MCP matrix where the agent tried to parse
# ``Toro....docx.kaos.json`` (application/json) with the PDF parser.
# Strip sidecars from the agent-visible listing at the tool-result
# post-processing step. The SPA reads sidecars directly via
# ``runtime.vfs.read`` — bypasses the agent-facing tool surface — so
# nothing internal breaks.
import kaos_core.tools as _kaos_core_tools  # noqa: E402

if not getattr(_kaos_core_tools.VFSListTool, "_spa_sidecar_filter_applied", False):
    _original_vfs_list_execute = _kaos_core_tools.VFSListTool.execute

    _SPA_SIDECAR_SUFFIXES: tuple[str, ...] = (".kaos.json", ".meta.json")

    async def _patched_vfs_list_execute(self, inputs, context=None):  # type: ignore[no-untyped-def]
        result = await _original_vfs_list_execute(self, inputs, context=context)
        # Tool errors short-circuit — passthrough.
        if result.isError:
            return result
        out = result.structuredContent
        if not isinstance(out, dict):
            return result
        items = out.get("items")
        if not isinstance(items, list):
            return result
        filtered = [
            p for p in items
            if not (isinstance(p, str) and p.endswith(_SPA_SIDECAR_SUFFIXES))
        ]
        if len(filtered) == len(items):
            return result  # nothing to strip — passthrough
        out["items"] = filtered
        out["count"] = len(filtered)
        # Re-render the agent-visible summary text (lives in
        # ``content[0].text`` for dict-shaped tool results — see
        # ``ToolResult.create_success``).
        path_label = out.get("path") or "/"
        new_summary = f"{len(filtered)} item(s) at '{path_label}'"
        if out.get("has_more"):
            new_summary += " (more available)"
        if result.content and hasattr(result.content[0], "text"):
            result.content[0].text = new_summary  # ty: ignore[invalid-assignment]
        return result

    # Method-level monkey-patch — `execute` is async on the class. Use
    # ``setattr`` so the unbound function becomes a bound method on
    # instances created later by ``register_kaos_tools``.

    _kaos_core_tools.VFSListTool.execute = _patched_vfs_list_execute  # ty: ignore[invalid-assignment]
    _kaos_core_tools.VFSListTool._spa_sidecar_filter_applied = True  # ty: ignore[unresolved-attribute]


def create_app(settings: AppSettings | None = None):
    """Build the FastAPI app. Tests call this with a custom ``settings``."""
    settings = settings or AppSettings()
    configure(settings)
    logger = app_logger("main")
    logger.info(
        "startup",
        extra={
            "env": settings.env,
            "default_model": settings.default_model,
            "vfs_path": str(settings.vfs_path),
        },
    )

    # kaos_ui.agents.build_chat_runtime: returns a disk-backed KaosRuntime
    # with kaos-core + (optional) kaos-pdf / kaos-office / kaos-content
    # read tools registered, plus the install_tool_bridge_runtime_patch
    # workaround applied idempotently. `tool_names` is the sorted catalog
    # used downstream by the system-prompt augmentation in stream_proxy.
    runtime, tool_names = build_chat_runtime(vfs_path=settings.vfs_path)

    # kaos-citations + kaos-source are not yet known to kaos-ui 0.1.0a1;
    # register them here. Promote into kaos_ui.agents.build_chat_runtime
    # alongside pdf/office/content when we cut kaos-ui 0.1.0a2 (task #92).
    with contextlib.suppress(ImportError):
        from kaos_citations import register_citations_tools

        register_citations_tools(runtime)
    with contextlib.suppress(ImportError):
        from kaos_source import register_source_tools

        register_source_tools(runtime)
    tool_names = tuple(sorted(runtime.tools.list_tools()))

    # TR-1 + TR-2: partition the now-complete catalog into kaos-agents
    # ToolGroups (web / documents / citations / vfs). SessionMeta.tool_set
    # uses these group names; the stream_proxy resolves the per-session
    # ceiling against the same registry.
    from kaos_ui.agents import register_kaos_tool_groups

    group_counts = register_kaos_tool_groups(runtime)
    logger.info(
        "registered %d kaos tools on runtime; groups=%s",
        len(tool_names),
        ", ".join(f"{g}={n}" for g, n in group_counts.items()) if group_counts else "(none)",
    )

    app = create_agent_app(runtime=runtime)

    app.state.app_settings = settings
    app.state.kaos_runtime = runtime
    app.state.kaos_tool_names = tool_names
    # SessionStore reuses the same VFS so our metadata sidecar lives
    # alongside kaos-agents memory under the same .kaos-vfs/ root.
    app.state.session_store = SessionStore(vfs=runtime.vfs)

    # In-process httpx client (ASGITransport) for the chat proxy.
    # Constructed eagerly so the first request doesn't wait, and
    # closed on shutdown via FastAPI's event hook.
    app.state.upstream_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://kaos-agents.internal",
        timeout=httpx.Timeout(None, connect=10.0),
    )

    # `on_event("shutdown")` is the deprecated-but-still-supported way
    # to hook teardown on a FastAPI app we don't own (create_agent_app
    # installed its own lifespan; composing a second one cleanly would
    # require subclassing).
    @app.on_event("shutdown")  # ty: ignore[deprecated]
    async def _close_upstream_client() -> None:
        client = getattr(app.state, "upstream_client", None)
        if client is not None:
            await client.aclose()

    app.include_router(health.router, prefix="/v1")
    app.include_router(models.router, prefix="/v1")
    app.include_router(chat.router, prefix="/v1/chat")
    # SSE resume endpoints (Stage 1) — share the /v1/chat prefix so the
    # ``require_auth`` dependency on every chat route also covers
    # ``/runs/active`` and ``/runs/{run_id}/events``.
    app.include_router(runs.router, prefix="/v1/chat")
    app.include_router(files.router, prefix="/v1/chat")
    app.include_router(citations.router, prefix="/v1/chat")
    # Plan Issue 10 layer 2 — message-level thumbs feedback.
    app.include_router(feedback.router, prefix="/v1/chat")
    # Plan Issue 6 — court-reproducibility replay endpoint.
    # Mounted under /v1/admin/ rather than /v1/chat/ because replay is
    # operator/audit tooling, not a per-tenant chat surface.
    app.include_router(replay.router, prefix="/v1/admin")
    # Plan Issue 10 L3 + L4 — Regenerate / Edit-prior rewind endpoints.
    app.include_router(messages.router, prefix="/v1/chat")

    return app


app = create_app()
