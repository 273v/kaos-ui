# kaos-ui

Project scaffolding for KAOS user-facing applications.

`kaos-ui` is the package that builds the front end of a KAOS app — terminal UI, native desktop, web SPA, web API, or Streamlit dashboard — using opinionated, safe-by-default templates that an AI agent or a human developer can drive with a single command.

## What you get

```bash
kaos-ui list
```

| Kind | Stack |
|---|---|
| `tui` | Textual |
| `desktop` | Tauri (preferred) or PyWebView |
| `web:spa` | Vite + React 19 + TanStack Router + Tailwind v4 + shadcn |
| `web:api` | FastAPI |
| `dashboard` | Streamlit (multipage) |

Every scaffold ships with: a uniform `Makefile` (`install`, `dev`, `test`, `up`, `down`, `doctor`), a hardened multi-stage `Dockerfile`, a `docker-compose.yml`, `.env.example`, `pre-commit-config.yaml`, a smoke test, and per-template `CLAUDE.md` / `AGENTS.md` so the agent editing inside knows the rules.

## Use

```bash
kaos-ui new web:spa my-app
cd my-app
make install
make doctor       # exits 0 on a fresh scaffold; if it doesn't, the template is broken
make up
```

Or through MCP — every CLI surface is exposed as a tool:

- `kaos-ui-list-templates`
- `kaos-ui-template-info`
- `kaos-ui-scaffold`
- `kaos-ui-doctor`

See `docs/QUICKSTART.md` for the vibe-coder walkthrough and `docs/PLAN.md` for the full design.

## Status

Phase 0 — package skeleton + lift-and-shift of existing templates from `kaos-mcp`. See `docs/TODO.md`.
