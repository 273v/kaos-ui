"""Per-request context plumbing for the SPA backend.

``kaos-agents`` >= 0.1.13 introduces :attr:`Runner.context_factory`, a
callable that builds a fresh :class:`KaosContext` per session at every
``turn`` / ``delegate`` / ``handoff`` entry. The SPA wants the
context's :attr:`default_vfs_namespace` to match the tenant-scoped
on-disk path that ``app/services/uploads.py`` writes to
(``sessions/{tenant}:{sid}/files/...`` under bearer-token auth, or
``sessions/{sid}/files/...`` in localhost-dev mode).

The kaos-agents Runner is constructed inside ``create_agent_app`` (see
``kaos_agents/api/server.py:461`` and ``:586``) BEFORE any request is
in scope — neither the host nor the request handler get to inject the
factory at construction time. To bridge the gap, this module exposes a
:class:`ContextVar` that the chat router sets at every request-entry
that drives the agent; the :class:`Runner.__init__` wrapper installed
in ``app.main`` reads that ContextVar to build the per-session factory
without the host having to plumb a callable through every layer.

Once kaos-agents threads ``context_factory`` through
``create_agent_app`` (anticipated 0.1.14), the :class:`Runner.__init__`
wrapper can be retired and the factory passed once at app build time;
this ContextVar surface stays unchanged because the factory still
needs the per-request tenant id.
"""

from __future__ import annotations

from contextvars import ContextVar

current_tenant_id: ContextVar[str | None] = ContextVar(
    "kaos_ui_spa.current_tenant_id", default=None
)
