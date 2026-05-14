"""Runtime registration for kaos-ui MCP tools.

The canonical entry point is ``register_ui_tools`` — matching the
``register_<short>_tools`` convention shared by ``kaos-pdf``
(``register_pdf_tools``), ``kaos-web`` (``register_web_tools``),
``kaos-office`` (``register_office_tools``), and ``kaos-reference``
(``register_reference_tools``).

``kaos-mcp/kaos_mcp/cli.py`` looks up the registration function as
``kaos_{name}.register_{name}_tools(runtime)``; the short-form name is
what makes ``kaos-mcp serve --module ui`` work.

``register_kaos_ui_tools`` is kept as a backwards-compatible alias for
the older naming used in design docs.
"""

from __future__ import annotations

from kaos_core import KaosRuntime

from kaos_ui.mcp.tools import (
    DoctorTool,
    ListTemplatesTool,
    ScaffoldTool,
    TemplateInfoTool,
)


def register_ui_tools(runtime: KaosRuntime) -> int:
    """Register all kaos-ui MCP tools onto ``runtime``. Returns count.

    Registered: ``kaos-ui-list-templates``, ``kaos-ui-template-info``,
    ``kaos-ui-scaffold``, ``kaos-ui-doctor``.

    The ``int`` return is the kaos-mcp ``--module`` loader contract:
    ``total += register_fn(runtime)`` in
    ``kaos-mcp/kaos_mcp/cli.py:_load_modules``.
    """
    tools = [ListTemplatesTool(), TemplateInfoTool(), ScaffoldTool(), DoctorTool()]
    for tool in tools:
        runtime.tools.register_tool(tool)
    return len(tools)


# Backwards-compatible alias. Design docs and earlier external code
# reference the longer form; both names register the same four tools
# and return the same int count.
register_kaos_ui_tools = register_ui_tools
