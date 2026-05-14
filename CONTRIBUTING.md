# Contributing to kaos-ui

`kaos-ui` is the project scaffolder for KAOS user-facing applications:
FastAPI APIs, web SPAs, Streamlit dashboards, Textual TUIs, and
standalone module/workflow packages. Contributions are welcome as
issues, evidence reports, and code changes — particularly ones that
tighten the link between what the scaffolder advertises and what the
scaffolded project actually does at runtime.

## Ground rules

1. **Templates ship working code.** Every shipping template must pass
   the per-template smoke matrix (`tests/integration/test_scaffold_*`).
   A template that scaffolds but doesn't boot is a release blocker.
2. **One source of truth per operation.** The CLI, the MCP tools, and
   the scaffolded `doctor` command all delegate to the same Python
   functions. Don't fork logic across layers.
3. **No AGPL/GPL dependencies — ever.** Either in `kaos-ui` itself or
   in any shipping template's `pyproject.toml`/`package.json`.
4. **Settings load at the edge.** `KaosUISettings` (and per-template
   env vars like `KAOS_UI_PYTHON_VERSION`) are resolved at the CLI or
   MCP tool boundary, not inside scaffolder internals.
5. **Errors are agent prompts.** Every tool / CLI / scaffolder error
   ships a `what` / `how_to_fix` / `alternative_tool` triple.

## How to contribute

### Reporting an issue

If a scaffold renders broken output, or a `kaos-ui doctor` check
returns a false negative, please open an issue with:

- The exact command you ran (e.g., `kaos-ui new web:spa myproj`)
- The kaos-ui version (`uv pip show kaos-ui`)
- The OS + Python version (`uname -a && python --version`)
- The unexpected output (stderr from the command, or the broken file)
- The expected output (what a working scaffold of the same kind should produce)

### Proposing a new template kind

New templates are welcome. Before opening a PR:

1. Confirm the kind has a clear use-case that's not covered by an
   existing kind. "Just like web:spa but with a different css framework"
   is usually a configuration switch on `web:spa`, not a new kind.
2. Build the template against the latest stable major of every external
   dependency. Pin to the minor in `pyproject.toml.tmpl` so consumers
   get bug-fix updates by default.
3. Add a per-template smoke test under `tests/integration/`. The
   test must scaffold the kind into a tmp directory, run the manifest's
   `post_install` chain, and exercise at least one user-facing path
   (e.g., for a web template: boot the dev server and curl /health).
4. Run the local quality gate (below) before pushing.

### Code contributions

1. Run the local quality gate before pushing:

   ```bash
   uv sync --group dev
   uv run ruff format kaos_ui tests
   uv run ruff check kaos_ui tests
   uv run ty check kaos_ui tests
   uv run pytest tests/ -q
   ```

2. New scaffolder features need a unit test (`tests/unit/`) covering
   the success path AND at least one error path.
3. New MCP tools need explicit `ToolAnnotations`, structured error
   envelopes (`_error_info`), and unit tests covering metadata +
   execute success + execute error.
4. Sign commits with `git commit -s` for the Developer Certificate
   of Origin.
5. Use conventional-commit-style messages (`feat:`, `fix:`, `chore:`,
   `docs:`, `ci:`, `test:`).
6. PR descriptions: state what changed, why, how it was tested, and
   whether the change affects shipping templates (those have a higher
   bar for backwards-compatibility).

## Reviewing template changes

A change to `kaos_ui/templates/<kind>/` is a soft-public-API change:
every consumer who scaffolds that kind picks up the change on their
next `kaos-ui new`. Test it the same way you'd test a function with
unknown callers.

The per-template smoke test (`tests/integration/test_scaffold_*.py`)
is the regression net. Keep it green.

## Security disclosures

See [`SECURITY.md`](SECURITY.md). Do not open public issues for
suspected vulnerabilities — use the private reporting channel.

## License

By submitting a contribution, you agree to license it under the
project's Apache 2.0 license (see [`LICENSE`](LICENSE)) and certify
that you have the right to do so under the
[Developer Certificate of Origin](https://developercertificate.org/),
which is signaled by the `Signed-off-by` trailer added by
`git commit -s`.
