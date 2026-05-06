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

### `tui:textual` to 100%

- [ ] Create `kaos_ui/templates/tui/textual/` (net-new)
- [ ] `pyproject.toml.tmpl` with Textual + KAOS deps pinned
- [ ] `{slug}/__main__.py`, `{slug}/app.py` ({Slug}App with screens + bindings)
- [ ] `{slug}/settings.py` — TUI variant (no auth_token, XDG-friendly VFS path)
- [ ] `{slug}/runtime.py`
- [ ] `{slug}/exceptions.py`
- [ ] `{slug}/styles.tcss`
- [ ] Three screens: chat, documents, settings
- [ ] `Makefile` (no up/down — TUIs aren't compose'd; optional Dockerfile)
- [ ] `.env.example`, `.gitignore`, `.pre-commit-config.yaml`
- [ ] `tests/test_smoke.py.tmpl` — `App.run_test()` async pilot, screen-switch assertions
- [ ] Manifest entry registered in `kaos_ui/manifest.py`
- [ ] Per-template `CLAUDE.md` + `AGENTS.md`
- [ ] kaos-ui repo: `tests/integration/test_scaffold_textual.py`
- [ ] `kaos_ui/doctor.py` — TUI-specific findings (LLM key present, terminal capabilities)

### `web:spa` (fullstack) to 100%

- [ ] Trim existing `kaos_ui/templates/web/spa/` to remove `apps/ssr/` (parked for Phase 4)
- [ ] Strip the existing minimal `backend/` and rebuild on kaos-core per spec
- [ ] Backend: `app/main.py.tmpl`, `settings.py.tmpl`, `runtime.py.tmpl`, `auth.py.tmpl`, middleware, `exceptions.py.tmpl`, `deps.py.tmpl`, `logging_setup.py.tmpl`
- [ ] Backend routers: `auth`, `health`, `sessions` (SSE), `documents`, `search`, `uploads`
- [ ] Backend services: `chat`, `documents`, `search`, `uploads`
- [ ] Alembic wired with initial migration
- [ ] Frontend: `apps/spa/` updated for React 19 + TanStack + Tailwind v4 + shadcn + Zod + Biome
- [ ] Frontend routes: login, chat, search, documents (+ `$documentId`), upload, settings
- [ ] OpenAPI codegen wired (`pnpm --filter spa codegen`)
- [ ] Streaming SSE consumer in `lib/streaming.ts`
- [ ] Auth context (httpOnly cookie flow)
- [ ] Shared `packages/ui/` updated with current shadcn primitives
- [ ] Caddyfile + docker-compose.yml + docker-compose.postgres.yml
- [ ] Backend tests: `test_health`, `test_auth`, `test_uploads`, `test_search`, `test_sessions`
- [ ] Frontend tests: vitest + RTL `pages.test.tsx`, `streaming.test.ts`
- [ ] `Makefile` with uniform verbs (parallel `make dev`)
- [ ] `.env.example`, `.gitignore`, `.editorconfig`, `.pre-commit-config.yaml`, `biome.json`
- [ ] Per-template `CLAUDE.md` + `AGENTS.md`
- [ ] Manifest entry already exists; update description + post_install + next_steps to match the new layout
- [ ] kaos-ui repo: `tests/integration/test_scaffold_spa.py` — scaffold → uv sync + pnpm install → run backend tests + pnpm build
- [ ] `kaos_ui/doctor.py` — SPA-specific findings (pnpm available, CORS not `*` in prod, codegen up to date)

### Phase 1 QA gate (after all three above)

- [ ] All Phase 0 gates still pass
- [ ] `./scripts/validate-platform.sh --profile ubuntu-26.04 --include-network --include-live` passes
- [ ] One real agent run logged per template in `tests/integration/manual-agent-runs.md`
- [ ] gitleaks scan on every template — clean
- [ ] trivy scan on every generated Dockerfile — no high/critical
- [ ] Apply 13 SDLC checklists per change

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
