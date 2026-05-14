# kaos-ui

Project scaffolding for KAOS user-facing applications.

`kaos-ui` is the package that builds the front end of a KAOS app — terminal UI, native desktop, web SPA, web API, or Streamlit dashboard — using opinionated, safe-by-default templates that an AI agent or a human developer can drive with a single command.

## What you get

```bash
kaos-ui list
```

| Kind | Stack | Phase |
|---|---|---|
| `web:spa` | Vite + React 19 + TanStack Router + Tailwind v4 + shadcn | shipping |
| `web:api` | FastAPI | shipping |
| `dashboard:streamlit` | Streamlit (multipage) | shipping |
| `tui:textual` | Textual | shipping |
| `module` | Python module skeleton + KAOS tool conventions | shipping |
| `workflow` | Single-file Python script with KAOS imports | shipping |
| `desktop` | Tauri or PyWebView | **planned (not yet registered)** |

Every shipping scaffold ships with: a uniform `Makefile` (`install`, `dev`, `test`, `up`, `down`, `doctor`), a hardened multi-stage `Dockerfile`, a `docker-compose.yml`, `.env.example`, a smoke test, and per-template `CLAUDE.md` / `AGENTS.md` so the agent editing inside knows the rules. (A `.pre-commit-config.yaml` is **not** in the template — generate one in your own project; the `single-user-chat` example ships one as reference.)

## Use

```bash
kaos-ui new web:spa my-app
cd my-app
make install
make doctor       # exits 0 on a fresh scaffold; if it doesn't, the template is broken
make up
```

The MCP tool surface (`kaos-ui-list-templates`, `kaos-ui-template-info`, `kaos-ui-scaffold`, `kaos-ui-doctor`) is **scoped for Phase 2** — the CLI surface ships today; the MCP wrappers are a stub at `kaos_ui/mcp/tools.py` and will arrive in a later release.

See `docs/QUICKSTART.md` for the vibe-coder walkthrough and `docs/PLAN.md` for the full design.

## Pre-built example

`examples/single-user-chat/` — a working reference app demonstrating
how to build a single-user agentic chat experience on top of
`kaos-agents`, reusing the design system and SSE plumbing from the
`web:spa` scaffold. Documentation-by-code; see
`examples/single-user-chat/README.md` for the 5-minute setup.

## Status

Phase 0 — package skeleton + lift-and-shift of existing templates from `kaos-mcp`. See `docs/TODO.md`.
