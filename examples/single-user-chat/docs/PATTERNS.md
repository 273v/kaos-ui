# single-user-chat — Patterns & Gotchas

> Living document. Update on every discovery. Last updated: 2026-05-14.

Catalog of non-obvious behavior, naming traps, version drift, and configuration footguns encountered while building this example. Each entry: symptom → cause → fix. Cite the source (file:line on PyPI install, repro command, etc.).

## Pre-flight discoveries (2026-05-14)

### P-001: `KAOS_AGENTS_API_ALLOW_UNAUTH_LOCALHOST` doesn't take effect — the real env var name is double-`API_`

**Symptom.** Setting `KAOS_AGENTS_API_ALLOW_UNAUTH_LOCALHOST=1` (as the kaos-agents error message instructs) does nothing — `create_app()` still raises `InsecureApiConfigurationError`.

**Cause.** `KaosAgentsApiSettings` (in `kaos_agents/api/settings.py` on PyPI install `kaos-agents==0.1.0a1`) has `env_prefix="KAOS_AGENTS_API_"` and a field named `api_allow_unauth_localhost`. pydantic-settings concatenates: `KAOS_AGENTS_API_` + `api_allow_unauth_localhost` → **`KAOS_AGENTS_API_API_ALLOW_UNAUTH_LOCALHOST`** (double `API_`). The error message in `insecure_startup_error()` is doc-bugged — it reports the single-`API_` form. Same trap applies to `KAOS_AGENTS_API_API_TOKEN` and `KAOS_AGENTS_API_API_CORS_ALLOW_ORIGINS`.

**Fix.** Use the double-`API_` form everywhere — `.env.example`, docker-compose, tests. Document the trap in our README troubleshooting table. Upstream issue worth filing against `kaos-agents`.

**Repro:**
```bash
env KAOS_AGENTS_API_API_ALLOW_UNAUTH_LOCALHOST=1 python -c \
  "from kaos_agents.api.server import create_app; create_app()"  # works
env KAOS_AGENTS_API_ALLOW_UNAUTH_LOCALHOST=1 python -c \
  "from kaos_agents.api.server import create_app; create_app()"  # fails
```

### P-002: `localhost-dev` mode rejects TestClient

**Symptom.** With `KAOS_AGENTS_API_API_ALLOW_UNAUTH_LOCALHOST=1`, all FastAPI `TestClient` requests return `401 {"detail":"Localhost-dev mode: only 127.0.0.1 / ::1 origins permitted..."}`.

**Cause.** TestClient sends its requests with a synthetic remote address that isn't `127.0.0.1` / `::1`. The localhost-dev gate rejects everything that isn't from one of those literal IPs.

**Fix.** **For tests, always use `KAOS_AGENTS_API_API_TOKEN`** with a 32+ char string and send the `Authorization: Bearer …` header — don't rely on the localhost-dev escape hatch. Our test fixtures set:

```python
@pytest.fixture
def client():
    os.environ["KAOS_AGENTS_API_API_TOKEN"] = "test-token-must-be-very-long-32-chars-min"
    from kaos_agents.api.server import create_app
    app = create_app()
    return TestClient(app, headers={"Authorization": f"Bearer test-token-must-be-very-long-32-chars-min"})
```

### P-003: `POST /v1/sessions` accepts only `session_id` — extras are silently ignored

**Symptom.** Passing `{"session_id": "x", "title": "demo", "model": "..."}` returns 200 but the title/model are not stored anywhere on the kaos-agents side.

**Cause.** `SessionCreateRequest` has exactly one required field, `session_id: str`. Extra body fields pass FastAPI validation (no `extra="forbid"`) but go nowhere.

**Fix.** **Generate the session ULID client-side** (or in our `POST /v1/chat/sessions` extension route) and pass it. Store all our metadata in the sidecar at `.kaos-vfs/single-user-chat/sessions/{id}/meta.json`. Don't try to ride kaos-agents' session-create body. This is the design ARCHITECTURE.md already specifies — but the doc previously implied kaos-agents *might* accept extra fields; it doesn't.

### P-004: `GET /v1/sessions/{id}` is 404 until first message lands

**Symptom.** Create a session via `POST /v1/sessions`, immediately `GET /v1/sessions/{id}` → 404 "No saved session found."

**Cause.** kaos-agents materializes a session on disk only after the first turn writes a message into SessionMemory. An "empty container" is not persisted by `POST /v1/sessions` alone.

**Fix.** **Don't enumerate sessions via kaos-agents.** Our `/v1/chat/sessions` lists our own metadata sidecar files, which exist from the moment we create the session — independent of whether the user has sent a message yet. Display the empty session as "Untitled" in the sidebar; the title is derived from the first user message once it lands.

### P-005: `POST /v1/sessions/{id}/messages` accepts rich per-turn overrides

**Symptom.** None — this is a green-light finding.

**Detail.** `MessageRequest` (verified) accepts:

```python
class MessageRequest:
    message: str                                   # required
    model: str | None = None                       # per-turn override
    pattern: str = "chat"                          # CHAT / PLAN / RESEARCH
    tools: list[str] = []                          # glob list, e.g. ["kaos-core-*"]
    max_cost_usd: float | None = None              # per-turn budget cap
    require_approval_for_tools: list[str] = []     # human-in-the-loop
    instructions: str | None = None                # SYSTEM PROMPT — NOT "system_prompt"
```

**Critical naming**: it's **`instructions`**, not `system_prompt`. Our metadata sidecar uses `system_prompt` (conventional) but we map `instructions = meta.system_prompt` at proxy time. Documented in ARCH § 4.4.

**Implication.** Our `/v1/chat/sessions/{id}/messages` proxy doesn't need to run `Runner.run()` in-process. It can HTTP-forward the body with all metadata applied as overrides. Simpler architecture.

### P-006: `Accept: application/json` returns a single aggregate response; SSE only when `Accept: text/event-stream`

**Symptom.** Test invocations of `POST /v1/sessions/{id}/messages` return JSON like `{"text":"...", "intent":"...", "turn_number":1, "tokens_used":94, "tool_calls":[], "budget_exceeded":false, "paused_for_approval":false}` when no Accept header is sent or Accept is `application/json`.

**Cause.** kaos-agents' route dispatches on Accept header. SSE is the streaming mode; JSON is the aggregate-await-then-return mode.

**Fix.** Useful for tests that want to verify behavior without parsing SSE. The SPA always uses `Accept: text/event-stream` for live streaming, but our integration tests can use JSON mode for fast assertions.

### P-007: Section list is 15, not 17 (verification doc drift)

**Symptom.** Live `POST /v1/sessions` response includes `sections: [...]` with **15** entries: `role, playbooks, plan_examples, messages, actions, documents, findings, plan_history, reflection, lessons, last_intent, working, planning_context, audit, graph`.

**Cause.** The earlier verification report listed 17 sections including `last_user_message` and `recent_actions`. Those are present as `MemoryType` enum values but are not separately persisted SNAPSHOT sections — they are derived/cached views or fallback aliases.

**Fix.** Documents claiming 17 sections are conservatively wrong; 15 is the persisted count. We only read MESSAGES anyway, so this is informational. ARCH.md § 6 updated.

### P-008: Tenant-isolated session ids — `{token_hash}:{user_session_id}`

**Symptom.** Session id requested as `"test-001"` becomes `"17f76e767749:test-001"` internally.

**Cause.** kaos-agents prefixes session ids with a hash of the bearer token, providing token-scoped tenant isolation (token A cannot see token B's sessions).

**Fix.** Our metadata sidecar uses the *user-facing* session id (without the prefix). Single-user deployment: this is invisible. If we ever expose multi-token, we'd need to align the namespacing.

### P-009: kaos-agents log lines pollute stdout in tests

**Symptom.** `INFO kaos.llm_client.providers.base [...]` etc. interleaved with pytest output.

**Cause.** `LoggingHook` and provider info logs go to root logger at INFO; pytest's `caplog` captures but doesn't silence.

**Fix.** Tests configure `logging.getLogger("kaos").setLevel(logging.WARNING)` in `conftest.py`. We don't suppress in production — that's where structured logging is most valuable.

## Phase 0 (2026-05-14)

### P-010: `packages/ui` ships sample-app stubs that break workspace typecheck

**Symptom.** After `make sync-ui` + `pnpm install`, `pnpm typecheck` fails at packages/ui:
```
src/lib/api.ts(3,29): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
```

**Cause.** The kaos-ui web:spa template's `packages/ui` ships three stub files for a never-implemented Documents demo: `src/lib/api.ts` (uses `import.meta.env.VITE_API_URL`), `src/hooks/use-documents.ts`, `src/types/document.ts`. These reference the consuming app's vite types but `packages/ui` itself doesn't depend on vite, so `tsc --noEmit` can't find `vite/client`.

**Fix.** `scripts/sync-ui.sh` deletes these three files after copy. Our example uses `apps/spa/src/lib/api-fetch.ts` for HTTP and has no Documents UI, so the stubs are dead weight. Documented as a planned upstream fix.

### P-011: TanStack Router plugin needs at least one route file before vite build

**Symptom.** `apps/spa typecheck` fails:
```
Error: rootRouteNode must not be undefined. Make sure you've added your root route into the route-tree.
```

**Cause.** `TanStackRouterVite` plugin (in `apps/spa/vite.config.ts`) generates `src/routeTree.gen.ts` from `src/routes/*.tsx` files. With no route files, it crashes at vite-build time — and our `typecheck` script runs `vite build` before `tsc --noEmit`.

**Fix.** Ship `src/routes/__root.tsx` (renders `<Outlet/>`) and `src/routes/index.tsx` (Phase 0 probe) from the start. The plugin auto-generates `routeTree.gen.ts` on every build; the file is gitignored.

### P-012: backend `uv sync` works first-try; transitively pulls 35+ packages

**Note.** `kaos-agents==0.1.0a1` + `kaos-core==0.1.0a6` + their friends resolve cleanly on Python 3.13. uv builds the lockfile against PyPI in seconds. No wheel-availability issues, no compiler dependencies.

## Phase 1 (2026-05-14)

### P-013: same-process HTTP loopback fails under `TestClient` — use `httpx.ASGITransport`

**Symptom.** Our `/v1/chat/sessions/{id}/messages` proxy POSTs to `http://127.0.0.1:8000/v1/sessions/{id}/messages` (kaos-agents) in the same process. Under `TestClient`, no port is bound, so the httpx call returns 405 / connection error.

**Cause.** `TestClient` is in-memory; there's no real server on 127.0.0.1:8000 during tests. Production deployments would work but pay the loopback TCP overhead.

**Fix.** Construct `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kaos-agents.internal")` at app startup and store on `app.state.upstream_client`. Both test and production code paths dispatch through the same ASGI app object — no real network, no port binding. Verified end-to-end with a live GPT-5 turn via TestClient + ASGITransport.

### P-014: `MessageRequest.tools=[]` means "no tools" — that's our `tools_enabled=False` mapping

**Detail.** Calling the upstream with `"tools": []` skips the tool runtime entirely (verified — kaos-agents responds normally without tool registration). Our `_build_forward_body` maps `tools_enabled=False → []` and `tools_enabled=True → ["*"]`. Don't accidentally send a glob like `["kaos-core-*"]` when off — that *would* enable the core tools.

### P-015: streamed payloads carry the full event class as a JSON field, not just the type

**Detail.** Each SSE `data:` line is a complete JSON dict whose fields mirror the kaos-agents event class. Sample (`text_delta`):
```json
{"timestamp": ..., "sequence": 2, "session_id": "082f692b250c:01KRK5...",
 "run_id": "run_3fb711...", "agent_id": null, "content": "'hello world'",
 "type": "text_delta"}
```
The frontend dispatches on `data.type` (string discriminator). All payload fields are first-class — we don't need a secondary lookup against `event:` line.

## Phase 2 (2026-05-14)

### P-016: TanStack Router needs `_auth.sessions.tsx` AND `_auth.sessions.index.tsx` once `index.tsx` exists at root

**Symptom.** With `index.tsx` (root `/`) and `_auth.tsx` (layout) both present, `pnpm typecheck` fails with `Conflicting configuration paths were found for the following routes: "/", "/"`.

**Cause.** A bare `_auth.tsx` resolves to `/` (the pathless `_` prefix is transparent), conflicting with `index.tsx`. The conflict resolves as soon as a real child route under `_auth.` exists (e.g., `_auth.sessions.tsx`) — the layout then represents its prefix instead of `/`.

**Fix.** Add at least one `_auth.*.tsx` child file before merging route changes. For the empty-state on `/sessions`, use `_auth.sessions.index.tsx` (it nests under `_auth.sessions.tsx`).

### P-017: `chrome-devtools-mcp` defaults to headful — needs `--headless` arg on headless boxes

**Symptom.** `mcp__chrome-devtools__new_page` errors with `Missing X server to start the headful browser. Either set headless to true or use xvfb-run`.

**Cause.** The MCP config in `~/.claude.json` launches `chrome-devtools-mcp` without `--headless`. The default is headful, which needs an X server.

**Fix.** Update `~/.claude.json` to add `--headless` to the `args` array:
```json
"chrome-devtools": {
  "type": "stdio",
  "command": "npx",
  "args": ["chrome-devtools-mcp@latest", "--headless"]
}
```
Then restart the Claude Code session so the MCP server picks up the new args. Until then, fall back to curl-based smoke verification through the vite proxy.

### P-018: stale `~/.cache/chrome-devtools-mcp/chrome-profile/SingletonLock` blocks new MCP Chrome

**Symptom.** `mcp__chrome-devtools__new_page` errors with `The browser is already running for /home/.../chrome-profile. Use --isolated to run multiple browser instances.`

**Cause.** A prior MCP-launched Chrome left a `SingletonLock` (symlink) and possibly the actual process. New MCP invocations refuse to clobber it.

**Fix.** Kill the stale Chrome (look for processes matching `--user-data-dir=$HOME/.cache/chrome-devtools-mcp/chrome-profile`) and `rm -f $HOME/.cache/chrome-devtools-mcp/chrome-profile/Singleton*` before reconnecting.

### P-019: Vite proxy correctly forwards Authorization + SSE without buffering

**Verified end-to-end (curl-smoke):** a `POST /v1/chat/sessions/{id}/messages` with `Accept: text/event-stream` through vite's `:5173/v1/*` proxy reached the backend, streamed all 6 expected events (`span`/`turn.start`, `intent_classified`, `text_delta`, `usage_observed`, `span`/`turn.complete`, `turn_summary`) with no buffering, and bumped the metadata sidecar's `message_count` to 1. The proxy is configured with default `flush_interval` behavior — no special directive needed; Vite's HTTP proxy passes through `text/event-stream` cleanly out of the box.
