# kaos-ui

> **Part of [Kelvin Agentic OS](https://kelvin.legal) (KAOS)** — open agentic
> infrastructure for legal work, built by
> [273 Ventures](https://273ventures.com).
> See the [full KAOS package map](https://github.com/273v) for the rest of the stack.

[![PyPI - Version](https://img.shields.io/pypi/v/kaos-ui)](https://pypi.org/project/kaos-ui/)
[![Python](https://img.shields.io/pypi/pyversions/kaos-ui)](https://pypi.org/project/kaos-ui/)
[![License](https://img.shields.io/pypi/l/kaos-ui)](https://github.com/273v/kaos-ui/blob/main/LICENSE)
[![CI](https://github.com/273v/kaos-ui/actions/workflows/ci.yml/badge.svg)](https://github.com/273v/kaos-ui/actions/workflows/ci.yml)

`kaos-ui` is the project scaffolder for KAOS user-facing applications. It
ships six production-ready templates — `web:api` (FastAPI), `web:spa`
(Vite + React + Tailwind v4 + shadcn/ui, kaos-agents-wired), `dashboard:streamlit`,
`tui:textual`, `module` (KAOS module package), and `workflow` (single-file
script) — and exposes the same scaffold/info/doctor lifecycle to MCP agents
through four read-only tools.

It is the dependency-light entry point every KAOS user-facing app builds
from. `kaos-ui` does not run servers, talk to LLMs, or render UI itself
— it produces working projects that do those things, with the
conventions and toolchain that the rest of the KAOS ecosystem assumes.

To expose `kaos-ui` over the Model Context Protocol, register its tools
on a `KaosRuntime` and serve it through the companion package
[`kaos-mcp`](https://github.com/273v/kaos-mcp) (ships separately).

## Install

```bash
uv add kaos-ui
# or
pip install kaos-ui
```

`kaos-ui` requires Python **3.13** or newer and has three runtime
dependencies (`kaos-core`, `pydantic`, `pydantic-settings`). Templates
that depend on `pnpm`, `cargo`, or `docker` declare those expectations
in their `kaos-ui-doctor` check; `kaos-ui` itself does not require them.

## Quick start

Scaffold a project from the CLI:

```bash
# Discover what's available
kaos-ui list

# See full detail (deps, env, post-install, next steps)
kaos-ui info web:spa

# Materialize a project
kaos-ui new web:spa myapp
cd myapp
make install     # runs the manifest's post_install chain
make dev         # boots the dev servers
```

Or drive the same lifecycle from Python:

```python
import asyncio
from pathlib import Path

from kaos_core import KaosRuntime
from kaos_ui import register_ui_tools, scaffold


async def main() -> None:
    # Use scaffold() directly:
    result = scaffold(template="workflow", name="demo", target_dir=Path("./demo"))
    print(f"created {len(result.files)} files in {result.target}")

    # Or register the MCP tools onto a runtime:
    runtime = KaosRuntime()
    n = register_ui_tools(runtime)
    print(f"registered {n} kaos-ui MCP tools")
    tool = runtime.tools.get_tool("kaos-ui-list-templates")
    res = await tool.execute({})
    print("templates:", res.structuredContent["count"])


asyncio.run(main())
```

## Concepts

The package is built around four small primitives.

| Concept | What it is |
|---|---|
| **`ScaffoldResult`** | Typed, frozen dataclass returned by `scaffold()`. `result.template` / `result.target` / `result.files` for attribute access; `result.to_dict()` for the serialization boundary into CLI JSON output or MCP `ToolResult.structuredContent`. |
| **`TemplateManifest`** | Per-kind metadata: description, tags, required env vars, post-install commands, next-step instructions, and the on-disk template directory. Registered via `register_template()`; looked up via `get_manifest(kind)`. |
| **`KaosUISettings`** | Typed settings (`KAOS_UI_` env prefix) for `python_version`, `node_version`, and `templates_dir` override. Resolved at the CLI/MCP boundary and threaded into `scaffold()` — never read mid-scaffolder. |
| **MCP tools** | Four `KaosTool` subclasses exposing the lifecycle to agents — `ListTemplatesTool`, `TemplateInfoTool`, `ScaffoldTool`, `DoctorTool`. Each ships explicit `ToolAnnotations` and structured error envelopes (`what` / `how_to_fix` / `alternative_tool`). |

## CLI

`kaos-ui` ships a `kaos-ui` CLI. Every structured command supports
`--json` for machine-readable output:

```bash
kaos-ui list                       # registered template kinds
kaos-ui list --json                # structured envelope: {"command": "list", ...}
kaos-ui info web:spa               # full manifest detail
kaos-ui info workflow --json
kaos-ui new web:spa myapp          # materialize a project
kaos-ui new web:spa myapp --dry-run  # plan without writing
kaos-ui doctor ./myapp             # health-check a scaffolded project
kaos-ui doctor . --json            # structured findings
```

## Compatibility & status

| Aspect | |
|---|---|
| **Python** | 3.13, 3.14 |
| **OS** | Linux, macOS, Windows (pure-Python wheel; no native code) |
| **Maturity** | Alpha. Public API is documented in `kaos_ui.__all__` (18 symbols). |
| **Stability policy** | Pre-1.0: minor bumps may change behaviour. Every change is documented in [`CHANGELOG.md`](CHANGELOG.md). Shipping template kinds (and their `post_install` + `next_steps` contracts), the MCP tool surface, and the `KAOS_UI_*` environment-variable namespace are public API. |
| **Test coverage** | 105 tests, 81% line coverage; the four MCP tools are 98%+ covered. |
| **Type checker** | Validated with [`ty`](https://docs.astral.sh/ty/), Astral's Python type checker. |

## Companion packages

`kaos-ui` is one of the packages in the
[Kelvin Agentic OS](https://kelvin.legal). The broader stack:

| Package | Layer | What it does |
|---|---|---|
| [`kaos-core`](https://github.com/273v/kaos-core) | Core | Foundational runtime, MCP-native types, registries, execution engine, VFS |
| [`kaos-content`](https://github.com/273v/kaos-content) | Core | Typed document AST: Block/Inline, provenance, views |
| [`kaos-mcp`](https://github.com/273v/kaos-mcp) | Bridge | FastMCP server, `kaos` management CLI, MCP resource templates |
| [`kaos-pdf`](https://github.com/273v/kaos-pdf) | Extraction | PDF → AST with provenance |
| [`kaos-web`](https://github.com/273v/kaos-web) | Extraction | Web extraction, browser automation, search, domain intelligence |
| [`kaos-office`](https://github.com/273v/kaos-office) | Extraction | DOCX / PPTX / XLSX readers + writers to AST |
| [`kaos-tabular`](https://github.com/273v/kaos-tabular) | Extraction | DuckDB-powered SQL analytics |
| [`kaos-source`](https://github.com/273v/kaos-source) | Data | Government + financial data connectors (Federal Register, eCFR, EDGAR, GovInfo, PACER, GLEIF) |
| [`kaos-llm-client`](https://github.com/273v/kaos-llm-client) | LLM | Multi-provider LLM transport |
| [`kaos-llm-core`](https://github.com/273v/kaos-llm-core) | LLM | Typed LLM programming (Signatures, Programs, Optimizers) |
| [`kaos-nlp-core`](https://github.com/273v/kaos-nlp-core) | Primitives (Rust) | High-performance NLP primitives |
| [`kaos-nlp-transformers`](https://github.com/273v/kaos-nlp-transformers) | ML | Dense embeddings + retrieval |
| [`kaos-graph`](https://github.com/273v/kaos-graph) | Primitives (Rust) | Graph algorithms + RDF/SPARQL |
| [`kaos-ml-core`](https://github.com/273v/kaos-ml-core) | Primitives (Rust) | Classical ML on the document AST |
| [`kaos-citations`](https://github.com/273v/kaos-citations) | Legal | Legal citation extraction, resolution, verification |
| [`kaos-agents`](https://github.com/273v/kaos-agents) | Agentic | Agent runtime, memory, recipes |
| [`kaos-reference`](https://github.com/273v/kaos-reference) | Sample | Reference module for module authors |

Packages depend on `kaos-core`; everything else is opt-in. Mix and match the
ones you need.

## Pre-built example

The repository ships a complete reference application under
[`examples/single-user-chat/`](examples/single-user-chat/) that
exercises the `web:spa` template end-to-end: bearer-token auth, SSE
streaming proxy with a read-only KAOS tool allowlist, persistent VFS,
markdown rendering with link sanitization, and a stop/cancel control.
It's the canonical proof that the scaffold output runs in anger.

## Development

```bash
git clone https://github.com/273v/kaos-ui
cd kaos-ui
uv sync --group dev
```

Install pre-commit hooks (recommended — they run the same checks as CI
on every commit, scoped to staged files):

```bash
uvx pre-commit install
uvx pre-commit run --all-files     # one-time full sweep
```

Manual QA commands (the same set CI runs):

```bash
uv run ruff format --check kaos_ui tests
uv run ruff check kaos_ui tests
uv run ty check kaos_ui tests
uv run pytest -m "not slow"
```

## Build from source

```bash
uv build
uv pip install dist/*.whl
```

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, quality gates, pull request expectations, and engineering
standards. By contributing you certify the
[Developer Certificate of Origin v1.1](https://developercertificate.org/) —
sign every commit with `git commit -s`. Please open an issue before starting
on a non-trivial change so we can align on scope.

## Security

For security issues, **please do not file a public issue**. Report privately
via [GitHub Private Vulnerability Reporting](https://github.com/273v/kaos-ui/security/advisories/new)
or email **security@273ventures.com**. See [SECURITY.md](SECURITY.md) for the
full disclosure policy.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 [273 Ventures LLC](https://273ventures.com).
Built for [kelvin.legal](https://kelvin.legal).
