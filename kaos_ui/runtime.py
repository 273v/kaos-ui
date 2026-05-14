"""Runtime registration for kaos-ui MCP tools.

Mirrors ``register_reference_tools`` in ``kaos-reference``: ``kaos-mcp``
serves anything registered onto a ``KaosRuntime``. kaos-ui does not
depend on kaos-mcp at runtime — the autoload entry point in
``kaos_ui.register_kaos_ui_tools`` is discovered by kaos-mcp's
``--module ui`` loader.
"""

from __future__ import annotations

from kaos_core import KaosRuntime

from kaos_ui.mcp.tools import (
    DoctorTool,
    ListTemplatesTool,
    ScaffoldTool,
    TemplateInfoTool,
)


def register_kaos_ui_tools(runtime: KaosRuntime) -> KaosRuntime:
    """Register all kaos-ui MCP tools onto ``runtime``.

    Registered: ``kaos-ui-list-templates``, ``kaos-ui-template-info``,
    ``kaos-ui-scaffold``, ``kaos-ui-doctor``.
    """
    runtime.tools.register_tool(ListTemplatesTool())
    runtime.tools.register_tool(TemplateInfoTool())
    runtime.tools.register_tool(ScaffoldTool())
    runtime.tools.register_tool(DoctorTool())
    return runtime
