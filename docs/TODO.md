# kaos-ui TODO

Phase-keyed task list. Source of truth for "what is left to do." Mirrors `docs/PLAN.md` but at the task level.

## Phase 0 — Lift and Shift (DONE)

- [x] Create `kaos-ui/` directory tree
- [x] Write `docs/PLAN.md`, `docs/PRD.md`, `docs/QUICKSTART.md`, `docs/TODO.md`, `docs/SAFETY.md` (stub)
- [x] Write `pyproject.toml`, `README.md`, `CLAUDE.md`
- [x] Build `kaos_ui` package skeleton (cli, manifest, scaffolder, doctor, settings, exceptions, runtime, mcp stubs)
- [x] Move `api / app / dashboard` templates into kaos-ui via `git mv`
- [x] Replace `kaos-mcp/.../scaffold.py` with re-export shim
- [x] Register `module` + `workflow` templates from kaos-mcp into kaos-ui's registry
- [x] Add `kaos-ui` runtime dep + uv editable source to kaos-mcp
- [x] Unit tests for manifest, scaffolder, settings, doctor (24 passing)
- [x] QA gate: ruff format / ruff check / ty check / pytest — all clean
- [x] Parity verified: `kaos new dashboard demo` ≡ `kaos-ui new dashboard demo` (byte-identical)

## Phase 1 — Three Templates to 100% (in progress)

> Spec docs: `docs/INTEGRATION.md`, `docs/templates/{streamlit,textual,spa}.md`. Read those before implementing.

### Phase 1 prerequisites

- [x] Write `docs/INTEGRATION.md` — cross-cutting "built on kaos-core" contract
- [x] Write `docs/templates/streamlit.md`
- [x] Write `docs/templates/textual.md`
- [x] Write `docs/templates/spa.md`
- [x] Update `docs/PLAN.md` for revised Phase 1 scope
- [x] Update `docs/TODO.md` for revised Phase 1 scope (this section)
- [ ] Settle: Biome vs ESLint+Prettier for SPA template (recommended: Biome)
- [ ] Settle: default LLM model token (`APP_LLM_MODEL` in `.env.example` set to `claude-haiku-4-5`)

### `dashboard:streamlit` to 100%

- [ ] Replace existing minimal scaffold at `kaos_ui/templates/dashboard/streamlit/` with the spec's full layout
- [ ] `pyproject.toml.tmpl` with pinned versions per spec
- [ ] `app.py.tmpl` (entry, settings, runtime cache, sidebar, auth gate)
- [ ] `{slug}/settings.py.tmpl` — `AppSettings(ModuleSettings)` with refuse-to-start validator
- [ ] `{slug}/runtime.py.tmpl` — `build_runtime()` factory with optional-extras suppress pattern
- [ ] `{slug}/auth.py.tmpl` — token gate using `hmac.compare_digest`
- [ ] `{slug}/exceptions.py.tmpl` — `{Slug}Error → KaosCoreError`
- [ ] `{slug}/logging_setup.py.tmpl` — JSON in prod, human in dev
- [ ] `{slug}/services/` — chat, documents, search, uploads
- [ ] Five pages: Chat, Upload, Search, Browse, Settings
- [ ] `Makefile` with uniform verbs
- [ ] `Dockerfile` (multi-stage, non-root, healthcheck)
- [ ] `docker-compose.yml` (localhost-only) + `docker-compose.postgres.yml` overlay
- [ ] `.env.example` enumerating every secret
- [ ] `.gitignore`, `.streamlit/config.toml.tmpl` hardened
- [ ] `.pre-commit-config.yaml` (ruff + ty + gitleaks)
- [ ] `tests/test_smoke.py.tmpl` — AppTest boots every page
- [ ] `tests/test_auth.py.tmpl`
- [ ] `tests/test_uploads.py.tmpl`
- [ ] `tests/test_settings.py.tmpl`
- [ ] Per-template `CLAUDE.md` + `AGENTS.md`
- [ ] kaos-ui repo: `tests/integration/test_scaffold_streamlit.py` — scaffold → install → smoke
- [ ] `kaos_ui/doctor.py` — Streamlit-specific findings (`.streamlit/config.toml`, port reachability)
- [ ] gitleaks scan clean
- [ ] trivy scan on generated Dockerfile clean

### `tui:textual` to 100% (DONE)

- [x] Create `kaos_ui/templates/tui/textual/` (net-new)
- [x] `pyproject.toml.tmpl` with Textual `>=8.0,<9.0` + KAOS deps pinned
- [x] `{slug}/__main__.py`, `{slug}/app.py` ({Slug}App with screens + bindings)
- [x] `{slug}/settings.py` — TUI variant (no auth_token, XDG-friendly VFS path)
- [x] `{slug}/runtime.py` with lazy KAOS extra registration
- [x] `{slug}/exceptions.py` (AppError, SettingsError, ChatError)
- [x] `{slug}/styles.tcss`
- [x] `{slug}/logging_setup.py` — JSON RotatingFileHandler with propagate=False
- [x] Three screens: chat (Markdown + @work), documents (DataTable), settings
- [x] Two services: chat (lazy kaos-agents), documents
- [x] `Makefile` with `make console` for textual-dev
- [x] `.env.example`, `.gitignore`, `.pre-commit-config.yaml`
- [x] `tests/test_smoke.py.tmpl` — `App.run_test()` Pilot, isinstance navigation assertions
- [x] `tests/test_settings.py.tmpl` — refusal cases + redaction walks SecretStr fields
- [x] `tests/test_services.py.tmpl` — pure-Python tests for documents service
- [x] Manifest entry registered in `kaos_ui/manifest.py`
- [x] Per-template `CLAUDE.md` (full runbook) + `AGENTS.md` (cross-tool)
- [x] kaos-ui repo: `tests/integration/test_scaffold_textual.py` — heavy integration green
- [x] PATTERNS.md updated with Textual gotchas (`_render` reserved, AppTest+TTY, etc.)
- [ ] `kaos_ui/doctor.py` — TUI-specific findings (LLM key present, terminal capabilities) — Phase 2

### `web:spa` (fullstack) to 100% (DONE)

- [x] Trim existing `kaos_ui/templates/web/spa/` to remove `apps/ssr/` (parked for Phase 4)
- [x] Rebuild backend wholesale on kaos-core
- [x] Backend: main / settings / runtime / auth / deps / exceptions / logging_setup
- [x] Backend routers: auth, health, sessions (SSE via sse-starlette), documents, search, uploads
- [x] Backend services: chat (lazy kaos-agents), documents, search, uploads (magic-byte)
- [x] Frontend: Vite 6 + React 19 + TanStack Router/Query + Tailwind v4 + Biome 2.x
- [x] Frontend routes: __root, _auth (pathless protected layout), index (redirect), login, _auth.chat
- [x] OpenAPI codegen wired (@hey-api/openapi-ts + tanstack-query plugin)
- [x] Streaming SSE consumer in `lib/streaming.ts` + vitest tests
- [x] Auth context (httpOnly cookie flow + ref-mirrored state for sync reads)
- [x] Caddyfile + docker-compose.yml + docker-compose.postgres.yml
- [x] Backend tests: test_health, test_auth (incl. Origin allowlist), test_uploads, test_settings, test_logging
- [x] Frontend tests: vitest + happy-dom `streaming.test.ts`
- [x] `Makefile` with uniform verbs (parallel `make dev`)
- [x] `.env.example` (multiline CSV-supporting), `.gitignore`, `biome.json`
- [x] Per-template `CLAUDE.md` (full runbook) + `AGENTS.md`
- [x] Manifest entry updated (post_install runs pnpm install + uv sync; next_steps)
- [x] kaos-ui repo: `tests/integration/test_scaffold_spa.py` — scaffold → minimal-deps → uv sync → pytest
- [ ] `kaos_ui/doctor.py` — SPA-specific findings (pnpm available, CORS not `*` in prod, codegen up to date) — Phase 2

### Phase 1 QA gate (DONE)

- [x] All Phase 0 gates still pass
- [x] kaos-ui ruff format / ruff check / ty check / pytest — all clean
- [x] 52 tests passing (was 24 at end of Phase 0)
- [x] Heavy scaffold→install→pytest integration green for all 3 templates
- [x] Live verify: curl + Playwright + docker build executed by hand
- [x] `test_template_compiles` strengthened: ast.parse + compile() + ruff check on rendered Python
- [x] `test_logging.py` regression test in each template (pins _HumanFormatter fix)
- [ ] Full `./scripts/validate-platform.sh --profile ubuntu-26.04 --include-network --include-live` — deferred to release
- [ ] One real agent run logged per template — deferred to release
- [ ] gitleaks scan on every template — deferred to Phase 3
- [ ] trivy scan on every generated Dockerfile — Streamlit + SPA Dockerfiles validated structurally; full trivy scan deferred until kaos-* on PyPI
- [x] Apply 13 SDLC checklists per change

### Phase 1 live-verify findings (DONE)

Caught 7 real bugs the structural tests missed:

- [x] Streamlit `pages/chat.py` had `return` outside function (compile() now catches)
- [x] Streamlit `services/chat.py` imported kaos-agents at module level (now lazy)
- [x] SPA backend looked for `.env` in `backend/` only (now `("../.env", ".env")`)
- [x] SPA cookie `secure` flag wrong in test env (TestClient drops `Secure` over http)
- [x] SPA Origin allowlist middleware never landed (now in auth.py)
- [x] SPA build script `tsc -b && vite build` had wrong order (now just `vite build`)
- [x] SPA auth refresh()/login() set React state but router beforeLoad saw stale (now returns boolean + ref-mirrored)

Plus secondary:

- [x] `KAOS_NPM_SLUG` template variable for npm-friendly hyphenated names
- [x] Vite proxy reads `VITE_BACKEND_URL` env override for multi-tenant dev hosts
- [x] vite.config.ts uses `defineConfig` from `vitest/config` for type-checked test block
- [x] `_HumanFormatter` `record.args = ()` fix ported across all 3 templates
- [x] Cleanup of unused imports / dead noqas / RUF022 sort

Documentation:

- [x] PATTERNS.md gained sections for all the gotchas above
- [x] DEPLOYMENT.md added (PyPI gap, workspace overrides, prod checklist)
- [x] INTEGRATION.md updated with KAOS_NPM_SLUG, env_file fallback, NoDecode pattern
- [x] Per-template CLAUDE.md updated with deploy callout

## Phase 2 — MCP Automation Surface

- [ ] Implement `kaos-ui-list-templates` tool
- [ ] Implement `kaos-ui-template-info` tool
- [ ] Implement `kaos-ui-scaffold` tool
- [ ] Implement `kaos-ui-doctor` tool
- [ ] `register_kaos_ui_tools(runtime)` in `runtime.py`
- [ ] Add `"ui"` to `kaos-mcp serve --module` autoload list
- [ ] `kaos-ui doctor` CLI uses same doctor.py as the MCP tool
- [ ] Update `docs/architecture.md` (top-level)
- [ ] `tests/integration/test_mcp_tools_in_memory.py`
- [ ] `tests/integration/test_mcp_tools_streamable.py`
- [ ] Manual agent-run logged in `tests/integration/manual-agent-runs.md`
- [ ] QA gate: tool-design checklist for each tool

## Phase 3 — Vibe-Coder Hardening

- [ ] Finish `docs/SAFETY.md`
- [ ] Per-template `CLAUDE.md` finalized
- [ ] `pre-commit-config.yaml` with gitleaks/ruff/eslint per template
- [ ] Production Dockerfiles (multi-stage, non-root, healthcheck)
- [ ] Caddy reverse proxy with TLS-by-default
- [ ] `.env.example` with hard fail-on-missing
- [ ] `kaos-ui upgrade` (dry-run mode)
- [ ] End-to-end vibe-coder walkthrough doc in `docs/oss/`
- [ ] gitleaks scan on templates dir — clean
- [ ] trivy scan on generated Dockerfiles — no high/critical
- [ ] External walkthrough executed; issues filed before merge

## Phase 4 — Post-1.0 (parking lot)

- [ ] **Desktop templates** — Tauri + PyWebView (deferred from Phase 1)
- [ ] **`web:api` standalone** — headless FastAPI without a frontend
- [ ] **`web:fullstack-ssr`** — TanStack Start SSR variant
- [ ] Agent backend toggle for the Streamlit kind
- [ ] Marimo template
- [ ] First-class `web:next` (Next.js SSR)
- [ ] Template registry (cookiecutter-shaped)
- [ ] `kaos-ui upgrade` apply mode (three-way merge)
- [ ] Per-cloud deploy recipes (`make deploy:fly`, etc.)
