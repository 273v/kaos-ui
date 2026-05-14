"""MCP tool implementations for kaos-ui.

Tools live in :mod:`kaos_ui.mcp.tools`. Registration onto a
:class:`kaos_core.KaosRuntime` happens via
:func:`kaos_ui.runtime.register_kaos_ui_tools`.
"""

from kaos_ui.mcp.tools import (
    DoctorTool,
    ListTemplatesTool,
    ScaffoldTool,
    TemplateInfoTool,
)

__all__ = [
    "DoctorTool",
    "ListTemplatesTool",
    "ScaffoldTool",
    "TemplateInfoTool",
]
