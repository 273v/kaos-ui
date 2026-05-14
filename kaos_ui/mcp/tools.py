"""MCP tools for kaos-ui.

Four read-only / one write tool exposing the scaffolder lifecycle to
MCP agents:

- ``kaos-ui-list-templates`` — read-only manifest registry.
- ``kaos-ui-template-info`` — read-only per-kind detail.
- ``kaos-ui-scaffold`` — writes files; returns a file manifest
  (never inline file contents — large outputs use the resource
  pattern; see ``docs/guides/mcp-data-flow.md``).
- ``kaos-ui-doctor`` — read-only structured findings for an existing
  scaffolded project.

All tools use flat ``ParameterSchema`` inputs and return ``ToolResult``
with agent-friendly errors. The implementations delegate to the same
functions the CLI calls, so there is exactly one source of truth per
operation.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from kaos_core import (
    KaosContext,
    KaosTool,
    ParameterSchema,
    TextContent,
    ToolAnnotations,
    ToolCapability,
    ToolCategory,
    ToolMetadata,
    ToolResult,
)
from kaos_core.types.results import ErrorInfo

from kaos_ui._version import __version__
from kaos_ui.doctor import run_doctor
from kaos_ui.exceptions import (
    ScaffoldError,
    TargetExistsError,
    UnknownTemplateError,
)
from kaos_ui.manifest import get_manifest, list_templates
from kaos_ui.scaffolder import scaffold
from kaos_ui.settings import KaosUISettings


def _metadata(
    *,
    name: str,
    description: str,
    capability: ToolCapability,
    input_schema: list[ParameterSchema],
    annotations: ToolAnnotations,
    output_schema: dict[str, Any] | None = None,
    side_effects: bool = False,
    idempotent: bool = True,
) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        description=description,
        category=ToolCategory.UTILITY,
        capability=capability,
        input_schema=input_schema,
        output_schema=output_schema,
        module_name="kaos-ui",
        version=__version__,
        annotations=annotations,
        side_effects=side_effects,
        idempotent=idempotent,
    )


def _error_info(
    *,
    code: str,
    what: str,
    how_to_fix: str,
    alternative_tool: str | None = None,
) -> ErrorInfo:
    """Agent-friendly error envelope: what / how_to_fix / alternative_tool.

    Routed through ``ErrorInfo`` so kaos-core preserves the structured
    payload in ``ToolResult.meta.error``; the assistant-visible string
    is the short ``what`` summary.
    """
    details: dict[str, Any] = {"what": what, "how_to_fix": how_to_fix}
    if alternative_tool is not None:
        details["alternative_tool"] = alternative_tool
    return ErrorInfo(code=code, message=what, details=details)


class ListTemplatesTool(KaosTool):
    """List every registered scaffold template kind."""

    @property
    def metadata(self) -> ToolMetadata:
        return _metadata(
            name="kaos-ui-list-templates",
            description=(
                "Return the registered scaffold template kinds with their "
                "descriptions and tags. Call this first when the user asks "
                "what kinds of projects kaos-ui can scaffold."
            ),
            capability=ToolCapability.QUERY,
            input_schema=[],
            output_schema={"type": "object"},
            annotations=ToolAnnotations(
                readOnlyHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        del inputs, context
        manifests = list_templates()
        items = [
            {
                "kind": m.kind,
                "description": m.description,
                "tags": list(m.tags),
                "required_env": list(m.required_env),
            }
            for m in manifests
        ]
        text = "\n".join(f"- {m['kind']}: {m['description']}" for m in items)
        return ToolResult(
            content=[TextContent(text=text)],
            structuredContent={"count": len(items), "templates": items},
        )


class TemplateInfoTool(KaosTool):
    """Return full manifest detail for one template kind."""

    @property
    def metadata(self) -> ToolMetadata:
        return _metadata(
            name="kaos-ui-template-info",
            description=(
                "Return the full manifest for one template kind: description, "
                "required env vars, post-install commands, next-step "
                "instructions, and tags. Pass the canonical "
                "``namespace:variant`` form (e.g. ``web:spa``) or a legacy "
                "alias. To discover valid kinds, call kaos-ui-list-templates."
            ),
            capability=ToolCapability.QUERY,
            input_schema=[
                ParameterSchema(
                    name="kind",
                    type="string",
                    description="Template kind. Canonical or legacy alias.",
                ),
            ],
            output_schema={"type": "object"},
            annotations=ToolAnnotations(
                readOnlyHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        del context
        kind = str(inputs.get("kind") or "").strip()
        if not kind:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what="missing required input 'kind'",
                    how_to_fix="pass a template kind like 'web:spa' or 'module'",
                    alternative_tool="kaos-ui-list-templates",
                )
            )
        try:
            m = get_manifest(kind)
        except UnknownTemplateError as exc:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what=f"unknown template kind {kind!r}: {exc}",
                    how_to_fix="call kaos-ui-list-templates to see valid kinds",
                    alternative_tool="kaos-ui-list-templates",
                )
            )
        info = {
            "kind": m.kind,
            "description": m.description,
            "tags": list(m.tags),
            "required_env": list(m.required_env),
            "post_install": list(m.post_install),
            "next_steps": list(m.next_steps),
        }
        text = (
            f"{m.kind} — {m.description}\n"
            f"Required env: {', '.join(info['required_env']) or '(none)'}\n"
            f"Post-install: {len(info['post_install'])} step(s)\n"
            f"Next steps: {len(info['next_steps'])} step(s)"
        )
        return ToolResult(
            content=[TextContent(text=text)],
            structuredContent=info,
        )


class ScaffoldTool(KaosTool):
    """Materialize a scaffold template into a target directory."""

    @property
    def metadata(self) -> ToolMetadata:
        return _metadata(
            name="kaos-ui-scaffold",
            description=(
                "Scaffold a project from a registered template into "
                "``target_dir`` (or ``./<name>`` when omitted). Returns a "
                "file manifest, never inline file contents. For "
                "non-destructive previews pass ``dry_run=true``. Call "
                "kaos-ui-list-templates first to discover valid kinds."
            ),
            capability=ToolCapability.GENERATE,
            input_schema=[
                ParameterSchema(name="template", type="string", description="Template kind."),
                ParameterSchema(name="name", type="string", description="Project name."),
                ParameterSchema(
                    name="target_dir",
                    type="string",
                    description="Target directory. Defaults to ./<name>.",
                    required=False,
                ),
                ParameterSchema(
                    name="ssr",
                    type="boolean",
                    description="For web:spa only — use TanStack Start (SSR).",
                    required=False,
                    default=False,
                ),
                ParameterSchema(
                    name="dry_run",
                    type="boolean",
                    description="If true, return the planned file list without writing.",
                    required=False,
                    default=False,
                ),
            ],
            output_schema={"type": "object"},
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
            side_effects=True,
            idempotent=False,
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        del context
        template = str(inputs.get("template") or "").strip()
        name = str(inputs.get("name") or "").strip()
        if not template or not name:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what="both 'template' and 'name' are required",
                    how_to_fix=(
                        "pass both inputs; see kaos-ui-list-templates for valid template kinds"
                    ),
                    alternative_tool="kaos-ui-list-templates",
                )
            )
        target_raw = inputs.get("target_dir")
        target = Path(str(target_raw)) if target_raw is not None else None
        ssr = bool(inputs.get("ssr", False))
        dry_run = bool(inputs.get("dry_run", False))

        try:
            result = scaffold(
                template=template,
                name=name,
                target_dir=target,
                ssr=ssr,
                dry_run=dry_run,
                settings=KaosUISettings(),
            )
        except UnknownTemplateError as exc:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what=f"unknown template {template!r}: {exc}",
                    how_to_fix="call kaos-ui-list-templates to see valid kinds",
                    alternative_tool="kaos-ui-list-templates",
                )
            )
        except TargetExistsError as exc:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what=str(exc),
                    how_to_fix="pass a different target_dir or remove the existing directory",
                    alternative_tool="kaos-ui-scaffold (with dry_run=true)",
                )
            )
        except ScaffoldError as exc:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what=str(exc),
                    how_to_fix="confirm target_dir is writable and disk is not full",
                    alternative_tool="kaos-ui-scaffold (with dry_run=true)",
                )
            )

        text = (
            f"Scaffolded {result.template} into {result.target} "
            f"({len(result.files)} files{', dry-run' if dry_run else ''})"
        )
        return ToolResult(
            content=[TextContent(text=text)],
            structuredContent=result.to_dict(),
        )


class DoctorTool(KaosTool):
    """Run kaos-ui's static health checks on a scaffolded project."""

    @property
    def metadata(self) -> ToolMetadata:
        return _metadata(
            name="kaos-ui-doctor",
            description=(
                "Run the kaos-ui health checks on an existing scaffolded "
                "project directory and return structured findings. Each "
                "finding includes severity, code, and a human-readable "
                "message; many include a remediation hint."
            ),
            capability=ToolCapability.ANALYZE,
            input_schema=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Filesystem path to the scaffolded project root.",
                ),
            ],
            output_schema={"type": "object"},
            annotations=ToolAnnotations(
                readOnlyHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        del context
        raw = inputs.get("path")
        if not raw:
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what="missing required input 'path'",
                    how_to_fix="pass the path to a scaffolded project root",
                )
            )
        path = Path(str(raw)).expanduser().resolve()
        if not path.is_dir():
            return ToolResult.create_error(
                _error_info(
                    code="kaos_ui_error",
                    what=f"path is not a directory: {path}",
                    how_to_fix="confirm the path exists; scaffold the project first",
                    alternative_tool="kaos-ui-scaffold",
                )
            )

        report = run_doctor(path)
        # DoctorReport is a frozen dataclass with a list[Finding] inside;
        # asdict() handles nested dataclasses correctly.
        structured = asdict(report)
        # Lossless single-line summary for the TextContent block.
        errors = sum(1 for f in report.findings if f.severity == "error")
        warnings = sum(1 for f in report.findings if f.severity == "warning")
        infos = sum(1 for f in report.findings if f.severity == "info")
        text = f"doctor: {path} — {errors} error(s), {warnings} warning(s), {infos} info"
        return ToolResult(
            content=[TextContent(text=text)],
            structuredContent=structured,
        )


__all__ = [
    "DoctorTool",
    "ListTemplatesTool",
    "ScaffoldTool",
    "TemplateInfoTool",
]
