# single-user-chat — Implementation Plan

> Status: draft. Last updated: 2026-05-14. Read `PRD.md`, `ARCHITECTURE.md`, and `UX-LANGUAGE.md` first.

## 0. Overview

Five phases. Each phase has:
- a goal sentence,
- an explicit deliverable list,
- a test gate that must be green before the next phase starts,
- a "definition of done" checklist.

We do not move forward with a yellow gate. If a phase blows out of scope, the work is reshaped into a later phase rather than padded in place.

### Resolved planning decisions (from verification pass)

These came out of running real `uv run --with kaos-agents …` snippets against PyPI and re-reading the live template. They unblock Phase 0:

- **Backend strategy:** mount `kaos_agents.api.server.create_app()` and add a thin extension layer (`/v1/models`, `/v1/chat/*`). See `ARCHITECTURE.md` § 4.
- **`packages/ui` consumption:** sync-on-install via `scripts/sync-ui.sh` that stamps placeholders. `packages/ui/` is `.gitignore`d. See `ARCHITECTURE.md` § 2.
- **`kaos-llm-core`** is NOT transitive from `kaos-agents==0.1.0a1`; must be in `[project].dependencies`.
- **Default model**: `anthropic:claude-haiku-4-5` (`KaosAgentSettings().default_llm_model`).
- **VFS path**: `.kaos-vfs/kaos-agents/sessions/{id}/memory.json` (note the `sessions/` segment), with `graph.ttl` alongside.
- **Wire event taxonomy**: 15 event classes; `span` carries `(subject, phase)`. Frontend dispatches on both.
- **Env literal**: `"development"` not `"dev"` (matches the template).

## Phase 0 — Skeleton (½–1 day)

**Goal:** Directory exists, dependency files in place, `packages/ui` sync-script working, toolchain proven.

### Deliverables

#### 0.1 Tree + dotfiles

- `kaos-ui/examples/single-user-chat/` directory created.
- All subdirs from `ARCHITECTURE.md` § 2 created. Empty `__init__.py` in backend Python packages only.
- `.env.example` with both `KAOS_AGENTS_API_*` and `APP_*` blocks (per `ARCHITECTURE.md` § 7) plus provider keys commented.
- `.gitignore` that lists `packages/ui/`, `apps/spa/src/api/client/`, `.kaos-vfs/`, `node_modules/`, `.venv/`, `__pycache__/`, `*.egg-info/`, `dist/`, lockfile temp files. Lift the rest from the template.
- `.pre-commit-config.yaml` — **NOT present in the template**, so generate one ourselves: `ruff format`, `ruff check`, `ty check` for Python; `biome check` for TS; trailing-newline + end-of-file hooks.
- `Makefile` with: `install`, `sync-ui`, `dev`, `test`, `up`, `down`, `doctor`, `codegen`. `install` depends on `sync-ui`. `dev` does **not** depend on `codegen` (mirrors the template — codegen is on-demand).

#### 0.2 sync-ui.sh

- `scripts/sync-ui.sh` per `ARCHITECTURE.md` § 2.
- Reads from `../../kaos_ui/templates/web/spa/packages/ui/`.
- Substitutes `{{KAOS_NPM_SLUG}}` → `kaos-chat-example`, `{{KAOS_PROJECT_NAME}}` → `Single-User Chat`.
- Idempotent (rm -rf + cp -r).
- Makefile: `make sync-ui` invokes it; first-run printed instruction tells the user to commit `pnpm-lock.yaml` after `make install`.

#### 0.3 Workspace + package.json

- `pnpm-workspace.yaml` listing `apps/*` and `packages/*` (the latter created by sync-ui). **Lift verbatim** the supply-chain settings: `minimumReleaseAge: 4320`, `blockExoticSubdeps: true`, `strictDepBuilds: true`, `dangerouslyAllowAllBuilds: false`, `savePrefix: ""`.
- Root `package.json` with `dev/build/install:ci/verify:deps/typecheck/lint/format/test` scripts (clone from template root `package.json`).
- `apps/spa/package.json` — same dep list as the template's SPA, with name `@kaos-chat-example/spa`, plus the additions in `ARCHITECTURE.md` § 8 (`markdown-it`, `date-fns`, `ulid`).
- `apps/spa/vite.config.ts`, `tsconfig.json`, `biome.json`, `openapi-ts.config.ts`, `index.html` — lift from template, run sync substitutions where needed.

#### 0.4 Backend pyproject

- `backend/pyproject.toml` — non-templated, hand-written from `ARCHITECTURE.md` § 8. **Verify every pin against `uv pip install --dry-run`** before committing.
- `backend/Dockerfile` — lift from `templates/web/spa/backend/Dockerfile`.
- Stub `backend/app/__init__.py`, `main.py` (with literally `from kaos_agents.api.server import create_app; app = create_app()` — single-line proof of life).

#### 0.5 Docker + Caddy

- `Caddyfile`, `docker-compose.yml`, `docker-compose.postgres.yml` — lifted from template. Confirm `flush_interval -1` is still on line 49.

### Test gate

```bash
cd kaos-ui/examples/single-user-chat
make sync-ui                                   # populates packages/ui
make install                                   # pnpm install + uv sync, no errors
cd backend && uv run python -c "from app.main import app; print(len(app.routes))"
                                               # → integer > 0 (proves create_app mounted)
cd ../apps/spa && pnpm typecheck               # zero TS errors
make doctor                                    # all green
```

### Definition of done

- [ ] `make sync-ui` produces a populated `packages/ui` with no `{{KAOS_*}}` placeholders remaining (grep verifies)
- [ ] `make install` exits 0 on a fresh checkout
- [ ] `from app.main import app` prints > 8 routes (create_app's session routes plus our stub health route)
- [ ] CI workflow runs `make sync-ui && make install && make typecheck`

---

## Phase 1 — Backend extension layer (1–1.5 days)

**Goal:** Our `/v1/models` and `/v1/chat/*` routes work and are tested. The kaos-agents-owned routes ride along untouched.

### Deliverables

#### 1.1 Settings + main.py

- `backend/app/settings.py` per `ARCHITECTURE.md` § 4.2 (`env: Literal["development","production","test"]`, `default_model`, `default_system_prompt`, `default_tools_enabled`, `turn_budget_usd`). Env prefix `APP_`.
- `backend/app/logging_setup.py` — `configure(settings)` + `app_logger(name)` wrap `kaos_core.logging.get_logger`. Lift from template.
- `backend/app/main.py` — mount `create_app()` and include our routers per `ARCHITECTURE.md` § 4.1.
- `backend/app/deps.py` — FastAPI dependencies, including `get_session_store(request)`.

#### 1.2 Model catalog

- `backend/app/services/catalog.py` — the static `MODELS` list. **Build it programmatically from `kaos_llm_client.cost.MODEL_PRICING`** so it can't rot independently:
  ```python
  from kaos_llm_client.cost import MODEL_PRICING, PRICING_LAST_UPDATED

  _CURATED = (
      ("anthropic:claude-haiku-4-5",  "Claude Haiku 4.5",   "Fast everyday chat"),
      ("anthropic:claude-sonnet-4-6", "Claude Sonnet 4.6",  "Balanced reasoning"),
      ("anthropic:claude-opus-4-7",   "Claude Opus 4.7",    "Maximum reasoning"),
      ("openai:gpt-5",                "GPT-5",              "OpenAI flagship"),
      ("openai:gpt-5.5",              "GPT-5.5",            "Latest OpenAI"),
      ("openai:gpt-4.1-mini",         "GPT-4.1 mini",       "Cheap, capable"),
      ("google:gemini-2.5-flash",     "Gemini 2.5 Flash",   "Long context, fast"),
      ("google:gemini-2.5-pro",       "Gemini 2.5 Pro",     "Long context, deep"),
      ("xai:grok-3",                  "Grok 3",             "Real-time leaning"),
      ("xai:grok-3-mini",             "Grok 3 mini",        "Cheap Grok"),
  )

  def build_models() -> list[ModelEntry]:
      registry_names = {strip_provider(k) for k in MODEL_PRICING}
      out = []
      for id_, label, hint in _CURATED:
          model_part = id_.split(":", 1)[1]
          if model_part not in registry_names:
              raise RuntimeError(f"catalog rot: {model_part!r} missing from MODEL_PRICING (last updated {PRICING_LAST_UPDATED})")
          out.append(ModelEntry(id=id_, label=label, provider=id_.split(":")[0], recommended_for=hint))
      return out
  ```
  The registry guard fails CI loudly if anyone adds a stale id.
- `backend/app/routers/models.py` — `GET /v1/models` returns `{"models": build_models()}`.

#### 1.3 Persistence

- `backend/app/persistence/sessions.py` per `ARCHITECTURE.md` § 4.6 (`SessionStore` over `kaos_core.artifacts.VirtualFileSystem`).
- `backend/app/models.py` — pydantic shapes for `ModelEntry`, `SessionMeta`, `SessionSummary`, `PatchMetaBody`, `SendMessageBody` per `ARCHITECTURE.md` § 3.3.

#### 1.4 Chat router + stream service

- `backend/app/routers/chat.py` — five endpoints per `ARCHITECTURE.md` § 4.3.
- `backend/app/services/stream_proxy.py` — `stream_via_runner(meta, runtime, message)` per `ARCHITECTURE.md` § 4.4. Builds an `Agent` per turn using `meta.system_prompt`, `meta.model`, `meta.tools_enabled`. Installs `LoggingHook()` only. **Verify in this phase: does kaos-agents' POST /v1/sessions/{id}/messages accept body fields for `model` and `system_prompt`?** If yes, we can choose between in-process delegation and HTTP proxy. Default to in-process (it's what the template does and removes the httpx dep).

#### 1.5 Tests

- `tests/unit/test_persistence.py` — round-trip CRUD against `tmp_path` VFS; archive + restore; list pagination.
- `tests/unit/test_catalog.py` — every catalog id parses as `provider:model` AND appears in `MODEL_PRICING` (the registry guard).
- `tests/unit/test_event_serialization.py` — `serialize_event` round-trip for each of the 15 event classes.
- `tests/integration/test_routes_no_llm.py` — `TestClient` against our `/v1/models`, `/v1/chat/sessions`, `/v1/chat/sessions/{id}/meta` routes. Run `create_app()` with `KAOS_AGENTS_API_ALLOW_UNAUTH_LOCALHOST=1` for the test fixture.
- `tests/integration/test_chat_stream_live.py` — POST to `/v1/chat/sessions/{id}/messages`, consume SSE, assert at least one `text_delta` AND a `turn_summary` arrive within 30s. Hits `anthropic:claude-haiku-4-5`. **Gated on `ANTHROPIC_API_KEY` and required for phase completion** per top-level CLAUDE.md § Testing Standards.
- `tests/integration/test_kaos_agents_passthrough.py` — assert kaos-agents' native routes (`POST /v1/sessions`, etc.) are mounted and respond. Smoke; protects against a breaking upstream change.

### Test gate

```bash
cd backend
ruff format app/ tests/
ruff check --fix app/ tests/
ty check app/ tests/
pytest tests/ -v -m "not live"
ANTHROPIC_API_KEY=… pytest tests/ -v -m live
```

All green. **Live test is mandatory** per top-level CLAUDE.md § Testing Standards.

### Definition of done

- [ ] `GET /v1/models` returns the 10-entry catalog with all entries pinned to `MODEL_PRICING`
- [ ] `GET /v1/chat/sessions` returns paginated metadata
- [ ] `PATCH /v1/chat/sessions/{id}/meta` round-trips
- [ ] `POST /v1/chat/sessions/{id}/messages` streams real Claude Haiku 4.5 tokens
- [ ] Session metadata persists across `uvicorn` restarts (kill + restart smoke)
- [ ] All linters clean; live test green

---

## Phase 2 — Frontend MVP (2–3 days)

**Goal:** Log in, see (empty) session list, start a new chat, send + stream, reload, persist, switch sessions. All UX decisions in `UX-LANGUAGE.md` already pinned — Phase 2 implements them faithfully.

### Deliverables

#### 2.1 Bootstrap

- `apps/spa/src/main.tsx` — TanStack Router + Query providers + auth context.
- `apps/spa/src/styles/main.css` — `@import "@kaos-chat-example/ui/styles/globals"` + font imports.
- `apps/spa/src/lib/api-fetch.ts`, `streaming.ts` — copy verbatim from synced template.

#### 2.2 Auth

- For v1: `localStorage`-backed bearer token, attached as `Authorization: Bearer …`. Per ARCHITECTURE § 4.5 (a). Document the cookie-upgrade path in `docs/PATTERNS.md`.
- `apps/spa/src/auth/context.tsx` — `login(token)` calls `GET /v1/models` as a probe (any kaos-agents-protected route works; we pick a cheap one); on success store token + redirect; on 401 show inline error.
- `apps/spa/src/routes/login.tsx` — single bearer-token form per `UX-LANGUAGE.md` § 4.x.
- `apps/spa/src/routes/_auth.tsx` — auth gate.

#### 2.3 App shell + sidebar

- `apps/spa/src/components/layout/AppShell.tsx`, `Sidebar.tsx`, `Header.tsx` — per `UX-LANGUAGE.md` § 4.1.
  - 264 px expanded, 56 px collapsed.
  - `localStorage`-persisted collapse state.
  - Cmd/Ctrl+B toggle binding.
- `apps/spa/src/components/sessions/SessionList.tsx`, `SessionListItem.tsx`, `NewChatButton.tsx` per `UX-LANGUAGE.md` § 4.6.
- `apps/spa/src/hooks/use-session-list.ts`, `use-create-session.ts`, `use-archive-session.ts`.

#### 2.4 Chat route + streaming

- `apps/spa/src/hooks/use-session.ts`, `use-send-message.ts` (owns SSE + AbortController).
- `apps/spa/src/lib/event-handler.ts` — exhaustive dispatch on the 15 event types + `span (subject, phase)` cartesian per `ARCHITECTURE.md` § 5.3.
- `apps/spa/src/lib/markdown.ts` — `markdown-it` with strict link sanitizer.
- `apps/spa/src/components/chat/Composer.tsx`, `Message.tsx`, `TurnStatus.tsx`, `UsageChip.tsx`, `ToolCallBlock.tsx`, `RightRail.tsx` per `UX-LANGUAGE.md` §§ 4.2–4.4.
- `apps/spa/src/routes/_auth.sessions.tsx`, `_auth.sessions.$id.tsx` — wires history hydrate + composer + streaming.

#### 2.5 Generated API client

- `pnpm codegen` against a running backend → `apps/spa/src/api/client/`.
- Generator: `@hey-api/openapi-ts` configured against `http://localhost:8000/openapi.json` (kaos-agents serves it).

#### 2.6 Tests

- `apps/spa/src/lib/event-handler.test.ts` — 15 + 7-span exhaustiveness.
- `apps/spa/src/lib/streaming.test.ts` — drive against a recorded SSE log.
- `apps/spa/src/routes/_auth.sessions.test.tsx` — list render + new-chat happy path.

### Test gate

```bash
cd apps/spa
pnpm lint
pnpm typecheck
pnpm test
cd ../..
make up           # backend + caddy + spa preview
# Manual: log in, send 2 messages across 2 sessions, reload, confirm persistence.
make down
```

### Definition of done

- [ ] Login → list → new chat → send → stream → reload → state intact
- [ ] Two sessions visible in sidebar; switching works
- [ ] All wire-level event types observed during a typical Haiku 4.5 turn (`text_delta`, `span`, `intent_classified`, `usage_observed`, `turn_summary`, `memory_event`) render correctly
- [ ] vitest + biome + tsc all green

---

## Phase 3 — Settings sheet + transcript export (1 day)

**Goal:** Per-session model, system prompt, tools toggle. Transcript export to Markdown + JSON. Composer chip + drawer paths both work.

### Deliverables

- `apps/spa/src/components/settings/SettingsSheet.tsx`, `ModelPicker.tsx`, `PromptEditor.tsx`, `ToolsToggle.tsx` per `UX-LANGUAGE.md` § 4.7.
- `apps/spa/src/hooks/use-models.ts`, `use-patch-meta.ts`.
- `apps/spa/src/lib/transcript.ts` — Markdown + JSON serializers (client-side).
- `apps/spa/src/components/sessions/SessionListItem.tsx` hover menu: Rename, Export → Markdown, Export → JSON, Delete.
- Sheet open/close state in URL: `?settings=open`.
- The model-picker chip in the composer is a separate trigger that opens the picker popover *inline*, without opening the full sheet — per `UX-LANGUAGE.md` § 4.3.

### Test gate

- `apps/spa/src/lib/transcript.test.ts` — Markdown + JSON round-trip on a fixture.
- E2E manual: pick a non-default model → send → confirm in `turn_summary` payload that the chosen model id was used.
- E2E manual: edit system prompt → send → instruction-following assertion.
- E2E manual: tools toggle on → ask a question that requires read-only tools (e.g., file inspection if available) → confirm a `span (subject=tool_call, phase=start)` fires.

### Definition of done

- [ ] Model picker shows the static catalog; PATCH round-trips; new model applies to next turn
- [ ] Custom system prompt persists across reloads and is applied per turn
- [ ] Tools toggle persists and is applied per turn
- [ ] Markdown + JSON exports valid for sessions with mixed user/assistant/error/tool messages

---

## Phase 4 — Full event surface + polish (1 day)

**Goal:** Every event class + every observed `(subject, phase)` combo renders deliberately. Accessibility, error states, debug overlay.

### Deliverables

- Render strategies for low-frequency events per `ARCHITECTURE.md` § 5.3: `thinking_delta`, `plan_proposed`, `citation_found`, `evidence_insufficient`, `grounding_refusal_triggered`, `budget_exceeded`, `tool_call_approval_required` (v1 stub).
- Debug overlay (hidden, `?debug=true`) that logs every raw event in a right-rail dev panel.
- Error states: backend-down banner with retry, mid-turn LLM error inline message, aborted turn "Stopped" chip.
- Accessibility pass per `UX-LANGUAGE.md` § 9:
  - Focus rings (1 px, do NOT bump to 2 px)
  - ARIA `role="log"` + `aria-live="polite"` on conversation surface
  - Keyboard: Cmd+K new chat, Cmd+B sidebar toggle, J/K navigate, Esc close drawer
  - `prefers-reduced-motion` disables the streaming caret blink
- Disclaimer line below composer per `UX-LANGUAGE.md` § 4.2.

### Test gate

- `pnpm test` includes a unit test per event type asserting a deliberate DOM node — no fall-through.
- Manual accessibility audit via DevTools accessibility tree + Lighthouse ≥ 95 on Accessibility.
- Manual cross-browser smoke: Chrome, Firefox, Safari (current versions).

### Definition of done

- [ ] 15 wire types + 7 span combos = 22 dispatch cases, all unit-tested with non-empty render
- [ ] Debug overlay renders raw events on `?debug=true`
- [ ] Lighthouse Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95
- [ ] README + screenshots committed

---

## Phase 5 — Documentation pass + CI (½ day)

**Goal:** A first-time reader can run the example end-to-end without help.

### Deliverables

- `docs/PATTERNS.md` — every gotcha from Phases 0–4 (sync-ui drift, model id rot, kaos-llm-core non-transitivity, env literal naming, `flush_interval -1`, cookie scheme, etc.).
- `docs/DEPLOYMENT.md` — mirror `kaos-ui/docs/DEPLOYMENT.md`: hostname/TLS notes, HSTS enable step, prod token strength rule, CORS origin override.
- `README.md` updated with screenshots, the 5-minute setup walkthrough, troubleshooting table, links to all `docs/`.
- `kaos-ui/README.md` updated with a "Pre-built Example" section pointing here.
- CI workflow that runs Phases 0–4's test gates against the published kaos-* PyPI versions.

### Test gate

A fresh-clone walkthrough by someone other than the author: clone, `cp .env.example .env`, set one API key, `make sync-ui && make install && make dev`, send first message inside 5 minutes.

### Definition of done

- [ ] Walkthrough succeeds for a first-time reader
- [ ] CI green
- [ ] All `docs/` cross-references resolve
- [ ] PATTERNS.md, DEPLOYMENT.md complete

---

## Cross-cutting concerns

### Versioning

- Each `docs/*.md` carries a "Last updated" at the top. Bump on substantive edits.
- `PRD.md` is frozen at the start of Phase 1; new goals require a `PRD.md` amendment.
- Re-verify model catalog (`scripts/check-catalog.sh` runs `python -c "from app.services.catalog import build_models; build_models()"` against the installed `kaos-llm-client`) on every CI run — fails loudly if a model id drifts out of `MODEL_PRICING`.

### Code-quality gates (every phase)

Per top-level CLAUDE.md § Code Quality:

```bash
# backend
ruff format app/ tests/
ruff check --fix app/ tests/
ty check app/ tests/
pytest tests/ -v

# frontend
pnpm lint
pnpm typecheck
pnpm test
```

### Pre-commit + safe-commit

Install the kaos-modules pre-commit hook (`../../scripts/install-git-hooks.sh`). Use `safe-commit.sh` for every commit. Don't `--no-verify` without a documented reason.

## Risk register

| Risk | Mitigation |
|---|---|
| `kaos-agents`'s `create_app()` shape changes between releases | `tests/integration/test_kaos_agents_passthrough.py` smoke-tests the native routes; CI fails loudly. Pin to `>=0.1.0a1,<0.2`. |
| `MODEL_PRICING` registry drifts → stale catalog | The catalog builder validates against the live registry on construction; CI runs it; failure aborts deploys. |
| `kaos-agents`'s `POST /v1/sessions/{id}/messages` doesn't accept per-turn body overrides | Default to in-process `Runner.run()` in our stream service — what the template already does. No external dep on httpx. |
| Template `packages/ui` drifts and sync-ui produces a bad copy | Sync-ui is idempotent; if it produces something broken, `make typecheck` catches it before runtime. |
| First-delta latency creeps over 2 s | Profile cold imports; keep `kaos-content/pdf/office` behind `tools_enabled=True`. |
| Live LLM tests flake on provider 500s | Retry once per CLAUDE.md; if persistent, document in commit message — never silently skip. |
| Cookie scheme mismatch (dev `secure=false`, prod `secure=true`) breaks login | Defer cookie auth to Phase 4+; v1 uses bearer + localStorage. Document the trade-off. |
| `kaos-llm-core` becomes transitive in a future `kaos-agents` release and our explicit pin becomes redundant | Harmless; the explicit pin is a future-proofing seatbelt. |

## What is explicitly NOT in any phase

- Worker queue, real database, SSR, mobile-first layout, i18n, third-party auth, analytics. See `PRD.md` § 4 + § 10.
- Tool-call approval UI (own example).
- Document upload + RAG (own example).
- Cookie-based auth flow (deferred to a Phase 4+ polish task, documented).
- Multi-user / per-user namespacing.

## Timeline (calendar, optimistic)

- Phase 0: ½–1 day
- Phase 1: 1–1.5 days
- Phase 2: 2–3 days
- Phase 3: 1 day
- Phase 4: 1 day
- Phase 5: ½ day

Total: **6–8 days** of focused work for one implementer, or **3–4 days** with two splitting backend/frontend. Roughly equal to the previous estimate but with most of Phase 1's route-implementation work replaced by Phase 0's `create_app()` mount + `sync-ui` scaffolding.
