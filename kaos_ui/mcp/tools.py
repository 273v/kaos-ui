"""MCP tools for kaos-ui (Phase 2).

Phase 0 leaves this file as a stub with the planned tool surface
documented inline. Phase 2 implements the four ``KaosTool`` subclasses
described below.

Tools (per ``docs/guides/tool-design.md``):

- ``kaos-ui-list-templates`` — read-only; returns the manifest registry.
  Annotations: readOnlyHint=True, idempotentHint=True, openWorldHint=False.

- ``kaos-ui-template-info`` — read-only; per-kind detail (deps, env vars,
  ports, post-install commands, what-not-to-touch list).
  Annotations: readOnlyHint=True, idempotentHint=True, openWorldHint=False.

- ``kaos-ui-scaffold`` — writes files; returns a manifest (file list +
  next-steps), never inline file contents (per mcp-data-flow.md).
  Annotations: readOnlyHint=False, destructiveHint=False,
  idempotentHint=False, openWorldHint=False.

- ``kaos-ui-doctor`` — read-only; structured findings with
  what/how_to_fix/alternative_tool keys.
  Annotations: readOnlyHint=True, idempotentHint=True, openWorldHint=False.

All tools use flat ``ParameterSchema`` inputs and return ``ToolResult``
with agent-friendly error messages on failure.
"""

from __future__ import annotations

# Phase 2 imports:
# from kaos_core import KaosTool
# from kaos_core.types.annotations import ToolAnnotations
# from kaos_core.types.metadata import ToolMetadata
# from kaos_core.types.parameters import ParameterSchema
# from kaos_core.types.result import ToolResult


__all__: list[str] = []
