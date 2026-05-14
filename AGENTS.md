# Repository Agent Guidance

## Scope

These instructions apply to this repository. They are the canonical
cross-tool guidance for coding agents working on `kaos-ui`; other
agent-specific files should defer here instead of duplicating policy.

For contributor workflow and detailed standards, read:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [Python design and architecture](docs/standards/python-design-and-architecture.md)
- [Code quality standards](docs/standards/code-quality-standards.md)
- [Engineering process](docs/standards/engineering-process.md)
- [Tests, fixtures, and CI](docs/standards/tests-fixtures-ci.md)

## Project Identity

- Distribution package: `kaos-ui`.
- Import package: `kaos_ui`.
- CLI entry point: `kaos-ui`.
- Runtime baseline: Python 3.13+.
- Tooling: `uv`, `ruff`, `ty` (not mypy), and `pytest`.
- Pure-Python project scaffolder. Six shipping templates
  (`web:api`, `web:spa`, `dashboard:streamlit`, `tui:textual`,
  `module`, `workflow`) + four read-only MCP tools
  (`kaos-ui-list-templates`, `kaos-ui-template-info`,
  `kaos-ui-scaffold`, `kaos-ui-doctor`).
- Do not add provider clients, LLM clients, document extractors, or
  server packages here. The runtime depends only on `kaos-core`,
  `pydantic`, and `pydantic-settings`.

## Setup

```bash
uv sync --group dev
uvx pre-commit install
```

Use `uv` for environment, test, build, and packaging commands. Avoid
manual dependency edits unless the task explicitly changes packaging.

## Local Checks

Run the relevant smallest check first while iterating. Before a PR, run
the documented quality gate:

```bash
uv run ruff format --check kaos_ui tests
uv run ruff check kaos_ui tests
uv run ty check kaos_ui tests
uv run pytest -m "not slow" --no-cov
```

When packaging, release behavior, or distribution metadata changes, also
run:

```bash
uv build
uvx --from twine twine check --strict dist/*
```

When touching a template under `kaos_ui/templates/`, run the
per-template integration test:

```bash
uv run pytest tests/integration/test_scaffold_<kind>.py -v -m ""
```

## Architecture Rules

- Templates are public API. A change to `kaos_ui/templates/<kind>/` is
  a soft-public-API change that every consumer picks up on the next
  `kaos-ui new`. Treat the per-template integration tests as the
  regression net.
- `post_install` chains use the in-house `cd X && y && z` parser. It
  refuses shell builtins (`export`, `set`, `source`, `.`, `if`, `fi`,
  `for`, `while`). Do not enable `shell=True` to add new shapes;
  extend the parser instead.
- MCP tools delegate to the same Python functions the CLI uses. Don't
  fork logic across the CLI and MCP layers.
- `KaosUISettings` resolves at the CLI/MCP edge. The scaffolder
  accepts settings as a parameter; do not read `os.environ` inside
  scaffolder internals.
- Keep the public Python API explicit and stable: `kaos_ui.__all__`,
  the CLI command set, the four MCP tool names, the
  `ScaffoldResult` dataclass shape, and the `KAOS_UI_*`
  environment-variable namespace are all public surface.
- Keep errors agent-friendly: every CLI / MCP / scaffolder error
  ships a `what` / `how_to_fix` / `alternative_tool` triple. No
  stack traces or internal paths in user-facing messages.

## Testing

- New public API or behavior needs tests through the real entry point.
- Bug fixes need regression tests.
- Security-sensitive behavior needs accepted and rejected cases with
  realistic inputs.
- Per-template integration tests live in
  `tests/integration/test_scaffold_<kind>.py` and exercise the full
  scaffold → post_install → boot path. Heavy tiers (`pnpm install`,
  multi-template smoke matrix) are marked `@pytest.mark.slow` and
  gated by `KAOS_UI_SKIP_HEAVY_INTEGRATION=1`.
- Do not use live network services or live credentials in normal tests.

## Security

- Never commit secrets, tokens, private keys, credentials, or `.env`
  files.
- Bound untrusted input by size, path, URL, recursion, time, or other
  appropriate limits.
- The post-install runner deliberately refuses shell builtins and
  never enables `shell=True`. Do not relax this.
- Do not add GPL, AGPL, unknown-license, non-commercial, or
  no-derivatives dependencies — neither in `kaos-ui` itself nor in any
  shipping template.
- Report suspected vulnerabilities through [SECURITY.md](SECURITY.md),
  not public issues.

## Commits, PRs, And Releases

- Keep one logical change per PR.
- Use conventional commit style and sign commits with `git commit -s`.
- Before committing, inspect `git status` and stage only intended files.
  Preserve unrelated user changes.
- Public API, CLI behavior, schema output, package metadata, template
  contents, security behavior, and deprecations require a
  `CHANGELOG.md` entry.
- Do not edit release metadata, generated files, `uv.lock`, or
  packaging files unless the task explicitly requires it.
- Do not force-push unless a maintainer explicitly requests it.
