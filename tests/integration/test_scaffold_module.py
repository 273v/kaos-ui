"""Integration test for the ``module`` template.

Scaffolds the template, imports the rendered package against the real
``kaos-core``, calls ``register_*_tools(KaosRuntime())``, and exercises
``execute()`` on the scaffolded ``ExampleTool``. Guards against template
drift relative to live ``kaos-core`` API shape — the structural
``test_template_compiles.py`` cannot catch semantic / runtime errors.

Marked ``integration`` because it imports the rendered package into
the running interpreter.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_module_template_scaffolds_imports_and_runs(tmp_path: Path) -> None:
    """End-to-end: scaffold, import, register, execute."""
    project = tmp_path / "demo_pkg"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "kaos_ui",
            "new",
            "module",
            "demo-pkg",
            "--target",
            str(project),
        ],
        check=True,
        cwd=tmp_path,
    )

    # The scaffolder slugifies "demo-pkg" → "demo_pkg" for the package
    # directory and module name.
    pkg_dir = project / "demo_pkg"
    assert pkg_dir.is_dir(), f"expected scaffolded package at {pkg_dir}"

    sys.path.insert(0, str(project))
    try:
        # Ensure no stale module state from prior test runs.
        for mod_name in list(sys.modules):
            if mod_name == "demo_pkg" or mod_name.startswith("demo_pkg."):
                del sys.modules[mod_name]

        demo_pkg = importlib.import_module("demo_pkg")
        tools_mod = importlib.import_module("demo_pkg.tools")

        # __version__ + register function are public exports.
        assert hasattr(demo_pkg, "__version__")
        assert hasattr(demo_pkg, "register_demo_pkg_tools")

        # ExampleTool conforms to the KaosTool ABC.
        from kaos_core import KaosRuntime, KaosTool

        tool = tools_mod.ExampleTool()
        assert isinstance(tool, KaosTool)

        meta = tool.metadata
        assert meta.name == "kaos-demo-pkg-example"
        assert meta.annotations is not None  # mandatory per tool-design.md
        assert meta.annotations.readOnlyHint is True

        # Registration round-trip against a real runtime.
        runtime = KaosRuntime()
        n = demo_pkg.register_demo_pkg_tools(runtime)
        assert n == 1
        assert any(
            t.metadata.name == "kaos-demo-pkg-example" for t in runtime.tools.list_tool_objects()
        )

        # execute() honors the inputs schema.
        result = await tool.execute({"message": "hi"})
        assert result.structuredContent == {"echo": "hi"}
    finally:
        sys.path.remove(str(project))
        for mod_name in list(sys.modules):
            if mod_name == "demo_pkg" or mod_name.startswith("demo_pkg."):
                del sys.modules[mod_name]
