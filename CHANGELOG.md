# Changelog

All notable changes to `kaos-ui` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — `@273v/kaos-ui-react` 0.1.0-alpha.0 (npm)

The React companion package now lives at
[`packages/kaos-ui-react/`](./packages/kaos-ui-react/) and is published
on npm as
[`@273v/kaos-ui-react`](https://www.npmjs.com/package/@273v/kaos-ui-react).
Templates depend on it via `^0.1.0-alpha.0`. The package owns the
chat surface, debug surface, hooks (`useSendMessage`, `useCitations`,
`useCostAggregation`, `useUploadFile`, `useBackfillFiles`, ...),
transport provider (`<KaosUIProvider>`), and the canonical
`KaosAgentEvent` discriminated union — so consuming SPAs never
hand-roll SSE event handling. See the package CHANGELOG for the full
feature list.

### Changed — `web:spa` template now consumes `@273v/kaos-ui-react`

- `kaos_ui/templates/web/spa/apps/spa/package.json` adds
  `@273v/kaos-ui-react` as a runtime dep.
- `main.tsx` wraps the app in `<KaosUIProvider transport={...}>` and
  imports the package's `styles.css`.
- `_auth.chat.tsx` is rewritten to consume `useSendMessage` plus
  `<Composer>` / `<Message>` / `<TurnStatus>` from
  `@273v/kaos-ui-react/chat`. The previous hand-rolled SSE handler
  used **obsolete kaos-agents event names** (`turn_start`,
  `tool_call_start`, `tool_call_result`, `step_start`,
  `turn_complete`); newly scaffolded SPAs ship with the current
  15-event union now.
- `apps/spa/tests/streaming.test.ts` re-targets
  `@273v/kaos-ui-react/lib` and asserts the current wire shape.
- Deletes the inline `apps/spa/src/lib/streaming.ts` plus
  `components/chat/{Composer,Message,TurnStatus,UsageChip}.tsx` —
  all now provided by the package.
- Deletes the stale `packages/ui/src/{lib/api.ts,hooks/use-documents.ts,types/document.ts}`
  stubs (wrong URLs, wrong response shapes; the example's
  `scripts/sync-ui.sh` was literally deleting them). The shadcn
  primitives in `packages/ui/src/components/ui/` stay.
- `packages/ui/package.json` drops `@tanstack/react-table` + `zod` —
  unused after the stub deletion.
- `CLAUDE.md` (template) updated to point contributors at the
  package's components/hooks instead of inlining their own.

### Fixed
- `register_kaos_ui_tools()` previously returned the `KaosRuntime`
  instance and was named with the long form `register_kaos_<name>_tools`.
  Both broke the `kaos-mcp serve --module ui` loader contract — it
  expects a function named `register_<name>_tools` (short form) that
  returns an `int` tool count (matching `kaos-pdf` / `kaos-web` /
  `kaos-office` / `kaos-reference`). The canonical entry point is now
  `kaos_ui.register_ui_tools` (returns `int`); the long form remains
  as a backwards-compatible alias.

### Added (other)
- Apache-2.0 license metadata in `pyproject.toml`, plus `LICENSE` and
  `NOTICE` files at the project root.
- `SECURITY.md` (90-day disclosure window, PVR primary), `CONTRIBUTING.md`,
  and `CODE_OF_CONDUCT.md` (professional conduct template).
- `[project.urls]` populated with all 5 entries (Homepage, Documentation,
  Repository, Issues, Changelog) and keywords for PyPI discovery.

## [0.1.0a1] — 2026-05-14

First public alpha.

### Added
- **Six shipping templates.** `web:api` (FastAPI), `web:spa`
  (Vite + React + Tailwind v4 + shadcn + FastAPI + Caddy + Docker,
  kaos-agents wired), `dashboard:streamlit`, `tui:textual`,
  `module` (KAOS module package with tools + CLI + serve + tests),
  `workflow` (single-file Python script).
- **`kaos-ui` CLI** with `list`, `info`, `new`, and `doctor` subcommands.
  Every structured command supports `--json` with a stable
  `command` + payload envelope per `docs/guides/cli-standard.md`.
- **Four MCP tools** registered onto a `KaosRuntime` via
  `register_kaos_ui_tools()`: `kaos-ui-list-templates`,
  `kaos-ui-template-info`, `kaos-ui-scaffold`, `kaos-ui-doctor`. All
  ship explicit `ToolAnnotations` and structured error envelopes
  (`what` / `how_to_fix` / `alternative_tool`).
- **Typed `ScaffoldResult`** dataclass — frozen, slotted, with a
  `to_dict()` boundary for JSON/MCP serialization.
- **`kaos_ui.agents` helper module** — `build_chat_runtime()`,
  `install_tool_bridge_runtime_patch()`, `augment_instructions()`,
  `NO_TOOLS_PATTERN` — so kaos-agents-on-FastAPI apps don't have to
  re-discover the same workarounds for kaos-agents 0.1.0a1.
- **`KaosUISettings`** (`KAOS_UI_` env prefix) — toolchain versions,
  `templates_dir` override, follows the canonical `ModuleSettings`
  pattern.
- **Post-install runner** supports `cd X && y && z` chains via shlex
  parsing without enabling a shell (refuses shell-builtin tokens).
- **`single-user-chat` example** under `examples/` — full end-to-end
  reference for the `web:spa` template, including bearer-token auth,
  SSE streaming proxy, read-only tool allowlist, persistent VFS, and
  markdown rendering with sanitized links.
- 105 tests passing (75 unit + 30 integration; 81% line coverage).

### Notes
- This is an **alpha**. The public Python API in `kaos_ui/__init__.py`
  is stable for the duration of the `0.1.x` line; experimental surfaces
  live under `kaos_ui.mcp.tools` and may evolve.

[Unreleased]: https://github.com/273v/kaos-ui/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a1
