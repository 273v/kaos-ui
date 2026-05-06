# kaos-ui Development Notes

## Required Checklists

Apply these checklist sources to every change in this module.

Python:
- `../docs/python/checklists/index.md`
- `../docs/python/checklists/01-research.md`
- `../docs/python/checklists/02-design.md`
- `../docs/python/checklists/03-implement.md`
- `../docs/python/checklists/04-test.md`
- `../docs/python/checklists/05-quality.md`
- `../docs/python/checklists/06-review.md`
- `../docs/python/checklists/07-commit.md`
- `../docs/python/checklists/08-debug.md`
- `../docs/python/checklists/09-optimize.md`
- `../docs/python/checklists/10-document.md`

Skip 11 (`retrieval-and-evaluation`), 12 (`benchmarking`), and 13 (`kaos-agent-retrieval`) — not applicable to scaffolding work.

## What this package owns

- Templates for every KAOS user-facing form factor (TUI, desktop, web SPA, web API, dashboard).
- The CLI (`kaos-ui`) that scaffolds, installs, and health-checks them.
- The MCP tools (`kaos-ui-list-templates`, `kaos-ui-template-info`, `kaos-ui-scaffold`, `kaos-ui-doctor`) that expose the same lifecycle to agents.
- Shared Docker/Caddy fragments under `kaos_ui/docker/shared/` reused across web templates.

## What this package does NOT own

- `module/` and `workflow/` templates — they are not UIs. They currently live in `kaos-mcp/kaos_mcp/management/templates/` and stay there until they get their own home (see PLAN §10 Open Questions).
- Cloud-deploy automation — recipes can sit in template `Makefile`s but `kaos deploy` is out of scope.
- A community template registry — Phase 4 may revisit.

## Integration

- Depends on `kaos-core` only (runtime, settings, logging, KaosTool).
- Does **not** depend on `kaos-mcp` at runtime. MCP exposure works via `register_kaos_ui_tools(runtime)` — the same pattern as kaos-pdf, kaos-web, kaos-reference.
- `kaos-mcp serve --module ui` autoloads via `kaos_ui.register_kaos_ui_tools`.

## Conventions

- CLI follows `../docs/guides/cli-standard.md`. Every structured command supports `--json` with `command` + `file`/`name` envelope keys.
- MCP tools follow `../docs/guides/tool-design.md`. Every tool sets `ToolAnnotations` explicitly. Errors include `what` / `how_to_fix` / `alternative_tool`.
- QA gate: `ruff format && ruff check --fix && ty check && pytest`. Mocked tests are not proof — every template kind has a live integration test that scaffolds → installs → builds → smoke-tests.
- Templates that import optional toolchains (cargo for Tauri, docker for compose) gate their integration tests with pytest markers (`desktop_native`, `slow`).
- Never add AGPL/GPL dependencies to templates or to this package.

## Settings

`KaosUISettings(env_prefix="KAOS_UI_")` follows the standard pattern from the top-level `CLAUDE.md` §"Configuration Hierarchy":

- `mode="before"` validators for legacy fallbacks.
- `SecretStr` for any future API keys.
- `extra="ignore"`.
- Settings are loaded at the CLI/tool boundary, never inside scaffolder internals.
