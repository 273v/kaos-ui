"""Unit coverage for kaos_ui.mcp.tools.

Exercises every tool's metadata + execute() success path + execute()
error path, plus the runtime registration entry point. Bridges to the
real scaffolder / doctor / manifest functions so a regression in those
is also caught here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from kaos_core import KaosRuntime, ToolAnnotations, ToolMetadata

from kaos_ui.mcp.tools import (
    DoctorTool,
    ListTemplatesTool,
    ScaffoldTool,
    TemplateInfoTool,
)
from kaos_ui.runtime import register_kaos_ui_tools

# ── metadata + registration ─────────────────────────────────────────


def test_register_kaos_ui_tools_adds_all_four() -> None:
    runtime = KaosRuntime()
    register_kaos_ui_tools(runtime)
    names = set(runtime.tools.list_tools())
    assert {
        "kaos-ui-list-templates",
        "kaos-ui-template-info",
        "kaos-ui-scaffold",
        "kaos-ui-doctor",
    }.issubset(names)


def test_every_tool_declares_explicit_annotations() -> None:
    """Per docs/guides/tool-design.md, ToolAnnotations are mandatory."""
    for tool_cls in (ListTemplatesTool, TemplateInfoTool, ScaffoldTool, DoctorTool):
        m: ToolMetadata = tool_cls().metadata
        assert m.annotations is not None, f"{tool_cls.__name__} missing ToolAnnotations"
        assert isinstance(m.annotations, ToolAnnotations)


def test_read_only_tools_advertise_read_only_hint() -> None:
    for tool_cls in (ListTemplatesTool, TemplateInfoTool, DoctorTool):
        m = tool_cls().metadata
        assert m.annotations is not None
        assert m.annotations.readOnlyHint is True


def test_scaffold_tool_is_marked_writer() -> None:
    m = ScaffoldTool().metadata
    assert m.annotations is not None
    assert m.annotations.readOnlyHint is False
    assert m.side_effects is True
    assert m.idempotent is False


# ── list-templates ──────────────────────────────────────────────────


def test_list_templates_returns_registry() -> None:
    result = asyncio.run(ListTemplatesTool().execute({}))
    assert result.isError is False
    structured = result.structuredContent
    assert structured is not None
    assert structured["count"] >= 1
    # Every known shipping kind appears.
    kinds = {t["kind"] for t in structured["templates"]}
    assert {"web:spa", "web:api", "workflow", "module"}.issubset(kinds)


# ── template-info ───────────────────────────────────────────────────


def test_template_info_returns_full_manifest() -> None:
    result = asyncio.run(TemplateInfoTool().execute({"kind": "web:spa"}))
    assert result.isError is False
    structured = result.structuredContent
    assert structured is not None
    assert structured["kind"] == "web:spa"
    for key in ("description", "tags", "required_env", "post_install", "next_steps"):
        assert key in structured


def test_template_info_missing_kind_returns_structured_error() -> None:
    result = asyncio.run(TemplateInfoTool().execute({}))
    assert result.isError is True
    assert result.meta is not None
    err = result.meta["error"]
    assert err["details"]["alternative_tool"] == "kaos-ui-list-templates"


def test_template_info_unknown_kind_returns_structured_error() -> None:
    result = asyncio.run(TemplateInfoTool().execute({"kind": "no-such-kind"}))
    assert result.isError is True
    assert result.meta is not None
    err = result.meta["error"]
    assert "no-such-kind" in err["details"]["what"]


# ── scaffold ────────────────────────────────────────────────────────


def test_scaffold_dry_run_returns_file_manifest(tmp_path: Path) -> None:
    out = tmp_path / "demo"
    result = asyncio.run(
        ScaffoldTool().execute(
            {
                "template": "workflow",
                "name": "demo",
                "target_dir": str(out),
                "dry_run": True,
            }
        )
    )
    assert result.isError is False
    structured = result.structuredContent
    assert structured is not None
    assert structured["dry_run"] is True
    assert structured["template"] == "workflow"
    assert len(structured["files"]) >= 1
    # Dry-run must NOT write to disk.
    assert not out.exists()


def test_scaffold_writes_files(tmp_path: Path) -> None:
    out = tmp_path / "demo"
    result = asyncio.run(
        ScaffoldTool().execute({"template": "workflow", "name": "demo", "target_dir": str(out)})
    )
    assert result.isError is False
    structured = result.structuredContent
    assert structured is not None
    assert structured["dry_run"] is False
    assert out.is_dir()
    assert any(out.iterdir()), "scaffolded directory should have at least one file"


def test_scaffold_missing_inputs_returns_structured_error() -> None:
    result = asyncio.run(ScaffoldTool().execute({"template": "workflow"}))
    assert result.isError is True
    assert result.meta is not None


def test_scaffold_unknown_template_returns_structured_error(tmp_path: Path) -> None:
    result = asyncio.run(
        ScaffoldTool().execute(
            {"template": "no-such-template", "name": "x", "target_dir": str(tmp_path / "y")}
        )
    )
    assert result.isError is True
    assert result.meta is not None


def test_scaffold_existing_nonempty_target_returns_structured_error(tmp_path: Path) -> None:
    out = tmp_path / "occupied"
    out.mkdir()
    (out / "junk.txt").write_text("blocking")
    result = asyncio.run(
        ScaffoldTool().execute({"template": "workflow", "name": "demo", "target_dir": str(out)})
    )
    assert result.isError is True
    assert result.meta is not None


# ── doctor ──────────────────────────────────────────────────────────


def test_doctor_missing_path_returns_structured_error() -> None:
    result = asyncio.run(DoctorTool().execute({}))
    assert result.isError is True
    assert result.meta is not None


def test_doctor_path_must_be_directory(tmp_path: Path) -> None:
    fake = tmp_path / "does-not-exist"
    result = asyncio.run(DoctorTool().execute({"path": str(fake)}))
    assert result.isError is True


def test_doctor_runs_on_a_scaffolded_project(tmp_path: Path) -> None:
    out = tmp_path / "demo"
    asyncio.run(
        ScaffoldTool().execute({"template": "workflow", "name": "demo", "target_dir": str(out)})
    )
    result = asyncio.run(DoctorTool().execute({"path": str(out)}))
    assert result.isError is False
    structured = result.structuredContent
    assert structured is not None
    # DoctorReport.asdict() preserves the findings list (may be empty).
    assert "findings" in structured


# ── integration: register + invoke via runtime ──────────────────────


@pytest.mark.parametrize("tool_name", ["kaos-ui-list-templates", "kaos-ui-doctor"])
def test_registered_tool_is_retrievable_by_name(tool_name: str) -> None:
    runtime = KaosRuntime()
    register_kaos_ui_tools(runtime)
    tool = runtime.tools.get_tool(tool_name)
    assert tool is not None
    assert tool.metadata.name == tool_name
