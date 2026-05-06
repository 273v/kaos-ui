"""Runtime registration for kaos-ui MCP tools.

Mirrors ``register_reference_tools`` in ``kaos-reference``. ``kaos-mcp``
serves anything registered onto a ``KaosRuntime`` — there is no direct
import dependency from kaos-ui to kaos-mcp.

Phase 0 ships the registration shape; Phase 2 lands the actual tool
implementations in ``kaos_ui.mcp.tools``.
"""

from __future__ import annotations

from kaos_core import KaosRuntime


def register_kaos_ui_tools(runtime: KaosRuntime) -> KaosRuntime:
    """Register all kaos-ui MCP tools onto ``runtime``.

    Phase 0: stubbed — returns the runtime unchanged. Phase 2 wires in
    ``kaos-ui-list-templates``, ``kaos-ui-template-info``,
    ``kaos-ui-scaffold``, and ``kaos-ui-doctor``.
    """
    # Phase 2:
    # from kaos_ui.mcp.tools import (
    #     KaosUIDoctor, KaosUIListTemplates, KaosUIScaffold, KaosUITemplateInfo,
    # )
    # runtime.tools.register(KaosUIListTemplates())
    # runtime.tools.register(KaosUITemplateInfo())
    # runtime.tools.register(KaosUIScaffold())
    # runtime.tools.register(KaosUIDoctor())
    return runtime
