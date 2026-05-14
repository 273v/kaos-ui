# Contributing to single-user-chat

This example is a reference consumer of the
[`@273v/kaos-ui-react`](../../../packages/kaos-ui-react/) workspace
package. Read [the root `CONTRIBUTING.md`](../../../CONTRIBUTING.md)
first — the rules below only describe extras specific to this
example.

## Local quality gate

From `examples/single-user-chat/`:

```bash
# Backend (Python 3.13+, uv-managed)
cd backend
uv sync --group dev
uv run ruff format --check app tests
uv run ruff check app tests
uv run ty check app tests
uv run pytest -q --no-cov

# Frontend (Node 22+, pnpm workspace at the repo root)
cd ../apps/spa
pnpm biome check src tests
pnpm tsc -b
pnpm vitest run
pnpm build
```

## Running the dev servers

```bash
make dev    # starts uvicorn + vite, prints URLs
make stop   # kills both
```

The Makefile exports `KAOS_AGENTS_API_API_TOKEN=demo-token-...` and
`APP_ENV=development`. Override either via env before invoking.

## Live testing via Chrome DevTools MCP

`chrome-devtools-mcp` launches Puppeteer-headful Chrome, which needs
an X display. The MCP server inherits env from when Claude Code
spawned it — on a GNOME desktop, that often misses `DISPLAY` and
`XAUTHORITY`, leading to `Missing X server to start the headful
browser` mid-session.

Workaround (one-time, per machine):

1. Save the wrapper at `~/.local/bin/chrome-devtools-mcp-with-x.sh`:
   ```sh
   #!/bin/sh
   uid=$(id -u)
   xauth=$(find "/run/user/${uid}" -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit 2>/dev/null || true)
   [ -z "${xauth}" ] && [ -f "${HOME}/.Xauthority" ] && xauth="${HOME}/.Xauthority"
   exec env DISPLAY="${DISPLAY:-:0}" ${xauth:+XAUTHORITY="${xauth}"} npx chrome-devtools-mcp@latest "$@"
   ```
2. `chmod +x ~/.local/bin/chrome-devtools-mcp-with-x.sh`
3. Edit `~/.claude.json` so the chrome-devtools `mcpServers` entry
   becomes:
   ```json
   "chrome-devtools": {
     "type": "stdio",
     "command": "/home/<you>/.local/bin/chrome-devtools-mcp-with-x.sh",
     "args": [],
     "env": {}
   }
   ```
4. Restart Claude Code.

Mutter regenerates the Xauth filename per login, so the wrapper
resolves it at invocation time. A non-GNOME session falls back to
`~/.Xauthority`.

## Adding a backend route

1. Pydantic shape in `app/models.py`.
2. Router file in `app/routers/<name>.py` — gate behind
   `Depends(require_auth)` unless explicitly public.
3. Mount in `app/main.py` under `/v1/chat`.
4. Integration test in `tests/integration/test_<name>.py` covering
   auth, validation, happy path, and one failure mode.

## Adding a frontend feature

1. Reach for `@273v/kaos-ui-react` first — most chat / debug surface
   already lives there. If your feature is genuinely reusable across
   chat apps, land it in the package and import here.
2. App-specific UI lives in `apps/spa/src/components/` (sidebar /
   settings / auth) and `apps/spa/src/routes/`.
3. Use `usePatchMeta` for any session-meta mutation so the cache
   invalidates correctly.

## Test data + secrets

- Never check in real API keys. Tests rely on the
  `KAOS_AGENTS_API_API_TOKEN` fixture (32-char dummy) configured in
  `tests/conftest.py`.
- Integration tests that need a parsed PDF use the
  `_MINIMAL_PDF` byte literal in `tests/integration/test_uploads.py`;
  do not pull from disk.
- LLM-dependent code paths (`summarize`, `summarize_session_title`)
  must short-circuit when no API key is set — failures here MUST be
  swallowed and logged, never propagated to the route response.
