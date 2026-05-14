# kaos-ui Engineering Standards

These are the durable engineering standards for `kaos-ui`. They are
the canonical source for code review, contribution review, and release
gating decisions. Quick-reference docs (the package `README.md` and
`CONTRIBUTING.md`) link here.

| File | Scope |
|------|-------|
| [code-quality-standards.md](code-quality-standards.md) | ruff/ty/pytest baselines, dependency hygiene, security checks, definition of done |
| [engineering-process.md](engineering-process.md) | Issue triage, branches, PRs, tags, releases, hotfixes |
| [python-design-and-architecture.md](python-design-and-architecture.md) | Public API surface, dependency boundaries, configuration patterns, errors, async, CLI |
| [tests-fixtures-ci.md](tests-fixtures-ci.md) | Test tiers, fixtures, coverage, CI workflows, release gates |

**Not applicable to `kaos-ui`:** Rust/PyO3 design standards. `kaos-ui`
is a pure-Python package; Rust standards live in their respective
Rust+PyO3 packages (`kaos-nlp-core`, `kaos-graph`, `kaos-ml-core`).

## Package-specific addenda

A handful of behaviours are specific to `kaos-ui` and worth flagging
on top of the generic standards above:

- **Templates are public API.** A change to `kaos_ui/templates/<kind>/`
  is a soft-public-API change — every consumer who runs
  `kaos-ui new <kind>` after the change picks it up. Treat the
  per-template integration tests in `tests/integration/test_scaffold_*.py`
  as the regression net.
- **`post_install` chains use `cd X && y` syntax.** The post-install
  runner hand-parses these chains without enabling a shell. Refused
  tokens: `export`, `set`, `source`, `.`, `if`, `fi`, `for`, `while`.
  Add to that list before introducing manifest commands that need them.
- **MCP tools delegate to CLI functions.** Each of the four tools in
  `kaos_ui.mcp.tools` calls the same Python function the CLI uses —
  there is exactly one source of truth per operation. Don't fork logic
  across the CLI and MCP layers.
- **`KaosUISettings` resolves at the edge.** The CLI and MCP tools
  instantiate settings; the scaffolder accepts them as a parameter.
  Never read `os.environ` from inside scaffolder internals.
