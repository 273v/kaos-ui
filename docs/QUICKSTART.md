# kaos-ui Quickstart

This guide gets you from "I have an idea" to "I have a running app" in under 5 minutes. It assumes you have an LLM agent (Claude Code, Codex, Gemini) connected to the KAOS MCP servers.

## Prerequisites

```bash
kaos doctor
```

This should report Python 3.14, Node 24, pnpm 11.1+ (for web kinds), and at least one LLM API key configured. If anything is missing, run:

```bash
kaos setup env
```

## Pick a kind

```bash
kaos-ui list
```

| Kind | What it builds | When to pick |
|---|---|---|
| `tui` | A keyboard-driven terminal app (Textual) | You live in the terminal; you want a focused tool |
| `desktop` | A native desktop app (Tauri) | You want a real installable program with menus and a window |
| `web:spa` | A browser app (Vite + React + Tailwind + shadcn) | You want to share a URL |
| `web:api` | A FastAPI backend, no UI | You're building an API for another front-end |
| `dashboard` | A Streamlit data app | You're a data person; you want sliders and charts |

If you don't know which to pick, ask your agent. It can read this guide and choose.

## Scaffold

```bash
kaos-ui new web:spa my-app
cd my-app
make install         # uv sync + pnpm install (or your kind's equivalent)
make doctor          # health-check the scaffold; should exit 0 immediately
make up              # boot the app
```

For `web:spa`, `pnpm install` creates the first lockfile under hardened
workspace settings: pnpm 11.1 pinned through Corepack, 72-hour release
cooldown, blocked exotic transitive specs, and reviewed dependency
build scripts only. Commit `pnpm-lock.yaml` after reviewing it; CI
should use `make install-ci && make verify-deps`.

## Through an agent

If you'd rather not type any of that, ask your agent:

> Build me a dashboard that tracks EPA enforcement actions.

The agent calls `kaos-ui-list-templates`, picks `dashboard`, calls `kaos-ui-scaffold` with a slug, runs `kaos-ui-doctor` to confirm the scaffold is clean, then begins editing the generated app. You watch.

## What you got

Every scaffold ships with the same shape:

- `Makefile` — `install`, `dev`, `test`, `up`, `down`, `doctor`. Same verbs across kinds.
- `.env.example` — every secret named. The app refuses to start without `.env`.
- `Dockerfile` + `docker-compose.yml` — non-root, slim, healthcheck.
- `CLAUDE.md` — agent rules: which files to never edit, where new code goes, when to run `make doctor`.
- `pre-commit-config.yaml` — formatters and security scanners pre-wired.
- A smoke test that proves the app boots.

## When it breaks

```bash
kaos-ui doctor           # in your project root
```

Returns a structured list of findings. Each finding has:

- `what` — what's wrong
- `how_to_fix` — exact command or change
- `alternative_tool` — another way if the first doesn't work

Paste the output to your agent. It can act on it directly.
