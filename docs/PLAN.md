# kaos-ui Plan

> Status: **Phase 0 — scaffolding the package and writing this plan.**
> Scope: project scaffolding for user-facing applications (TUI, desktop, web, dashboard) generated and operated through the same agentic workflow as the rest of KAOS.
> Owner: 273 Ventures.
> Audience: agents driving `kaos new` flows, and human builders ("vibe coders") shipping working apps on top of KAOS infrastructure.

---

## 1. Purpose

`kaos-ui` is the package that scaffolds, configures, and validates user-facing applications generated on top of the KAOS platform. It owns:

1. **Templates** for every form factor a KAOS app can ship in: terminal UI (Textual), desktop (Tauri or PyWebView), web SPA (Vite + React + TanStack + Tailwind + shadcn), web backend (FastAPI), and dashboard (Streamlit).
2. **Automation** to materialize, install, run, and health-check those templates: a `kaos-ui` CLI, MCP tools, Dockerfiles, docker-compose orchestration, and per-template `Makefile` task runners.
3. **Agentic guardrails** so an inexperienced "vibe coder" — guided by an LLM agent — can scaffold a safe, robust application by default without having to author auth, CORS, CSP, secret handling, or Dockerfile hardening from scratch.

`kaos-ui` is the new home for everything currently sitting under `kaos-mcp/kaos_mcp/management/templates/{api,app,dashboard}` and the `scaffold.py` logic that drives them. `kaos-mcp` shrinks back to an MCP bridge.

---

## 2. Why this lives outside kaos-mcp

The `kaos-mcp` package is the FastMCP bridge: tool registration, content/tabular resource templates, streamable HTTP, log bridging, MCP adapters. Project scaffolding is a different concern: it has nothing to do with MCP, it produces files on disk, and a user can scaffold a Streamlit dashboard or FastAPI service that never speaks MCP.

Scaffolding ended up in `kaos-mcp/kaos_mcp/management/` for historical reasons — the umbrella `kaos` CLI was first introduced there because the earliest commands were `kaos setup claude` and `kaos doctor`. That coupling is an accident, not architecture. `kaos-ui` corrects it.

The umbrella `kaos` CLI binary is a separate decision, tracked under [Open Questions](#10-open-questions). The plan below assumes `kaos-ui` exposes its own `kaos-ui` console script and that the unified `kaos` CLI either delegates to it (current state) or is moved out of `kaos-mcp` (future state).

---

## 3. Alignment With Top-Level Guidance

This package follows the same rules as every other KAOS module. Each rule below is sourced from a top-level doc, and the "Where applied" column points at the section of this plan or the package layout that enforces it.

| Source doc | Rule | Where applied in kaos-ui |
|---|---|---|
| `docs/guides/code-quality.md` | `ruff format` + `ruff check --fix` + `ty check` + `pytest` is the mandatory QA sequence; `mypy` is not equivalent | Phase QA gates; CI integration in `scripts/validate-platform.sh` |
| `docs/guides/cli-standard.md` | `kaos-<package>` console script + `__main__.py`; `main(argv)` signature; `--json` envelope with `command` + `file` keys; 1-based pages; errors to stderr | `kaos_ui/cli.py`, `kaos_ui/__main__.py`, every subcommand |
| `docs/guides/tool-design.md` | `ToolAnnotations` mandatory; agent-friendly errors (what / how / alternative); flat inputs; `kaos-{module}-{action}` naming with ≥3 segments | `kaos_ui/mcp/tools.py` — see [§5.4](#54-mcp-tools) |
| `docs/guides/mcp-data-flow.md` | Large outputs move by handle, not value; resources for data, tools for actions; chunked reads | `kaos-ui-scaffold` returns a manifest (file list + target dir), not file contents |
| `docs/guides/platform-validation.md` | Live tier (`--include-live --include-network`) is the acceptance gate; mocked unit tests are not proof | [§7](#7-testing--qa-strategy) — every template has a live "scaffold → install → build → smoke" integration test |
| `CLAUDE.md` (top-level) | `ModuleSettings` for config; `SecretStr` for keys; structured logging via `kaos_core.logging.get_logger`; agent-friendly errors; non-destructive merges | `KaosUISettings` class; never `os.environ` in tool internals; `kaos_ui` logger namespace |
| `CLAUDE.md` (top-level) | "Never add AGPL/GPL dependencies" | Tauri (MIT/Apache), Textual (MIT), Vite (MIT), Streamlit (Apache 2.0), FastAPI (MIT) — all permissive |
| `docs/python/checklists/*` | 13 SDLC checklists (research → optimize → document) applied per change | Each phase below ends with the checklist gate |

If any of the above stops being true, `kaos-ui` is broken and the responsible phase reopens.

---

## 4. Integration Points

### 4.1 kaos-core

`kaos-ui` depends on `kaos-core` for runtime, settings, logging, and tool primitives — same as every other tool-bearing module.

- `KaosRuntime` — `kaos_ui` registers its MCP tools onto a runtime via `register_kaos_ui_tools(runtime)` (mirrors `register_reference_tools` in `kaos-reference`).
- `KaosTool` ABC — every MCP tool inherits this. Inputs go through `ParameterSchema`, outputs through `ToolResult`.
- `ModuleSettings` — `KaosUISettings(env_prefix="KAOS_UI_")` resolves template directory overrides, scaffold defaults (Python/Node version pins), and registry URLs (future). Follows the validator pattern from `CLAUDE.md` §"Configuration Hierarchy" — `mode="before"` validators, `SecretStr` for any future API keys, `extra="ignore"`.
- `kaos_core.logging.get_logger("kaos.ui.scaffolder")` for all module logging. No bare `logging.getLogger`.
- Errors inherit from a per-module base (`KaosUIError`) which itself inherits from `KaosCoreError` — same pattern as kaos-pdf, kaos-web, kaos-source.

### 4.2 kaos-mcp

`kaos-ui` does **not** import from `kaos-mcp` at runtime. The MCP tools live in `kaos_ui/mcp/tools.py` as `KaosTool` subclasses. They get exposed over MCP exactly the way every other module's tools do — by being registered onto a `KaosRuntime` that `kaos-mcp` happens to be serving.

Concretely:

- `kaos-mcp serve --module ui` works the moment `kaos-ui` is installed and `register_kaos_ui_tools(runtime)` is wired up (same pattern as `kaos-pdf`, `kaos-web`, etc.).
- The unified `kaos new <kind> <name>` command in `kaos-mcp/kaos_mcp/management/cli.py` is rewritten to import `from kaos_ui.scaffolder import scaffold, list_templates` and delegate. This is a thin adapter — no template content lives in `kaos-mcp` after Phase 0.
- An `kaos-ui` console script does the same job standalone for users who installed `kaos-ui` without `kaos-mcp`.

This means two ways to drive scaffolding, both of which the user explicitly asked for:

1. **Local CLI** (`kaos-ui new web myapp` / `kaos new web myapp`) — runs in a developer terminal, handles `--dry-run`, `--json`, and post-install hooks.
2. **MCP tools** (`kaos-ui-list-templates`, `kaos-ui-scaffold`, `kaos-ui-doctor`, `kaos-ui-template-info`) — drive the same code path from any MCP client (Claude Code, Codex, Gemini, ChatGPT).

### 4.3 kaos-content (optional)

For the dashboard and web templates, the wired-in backend uses `kaos-content`'s `ContentDocument` model when working with extracted documents. `kaos-ui` does not depend on `kaos-content` directly — the dependency lives in the *generated* project's `pyproject.toml`, not in kaos-ui itself.

### 4.4 kaos-agents (optional)

The web/dashboard templates ship with an "agent backend" toggle that wires the generated FastAPI app to `kaos-agents` (Runner + SessionMemory). Same shape: kaos-ui stays light; the dependency goes in the generated project.

---

## 5. Module Layout

```
kaos-ui/
├── pyproject.toml                         # name=kaos-ui; module=kaos_ui; hatchling
├── README.md
├── CLAUDE.md                              # checklists pointer + module-specific notes
├── docs/
│   ├── PLAN.md                            # this file
│   ├── PRD.md                             # product requirements
│   ├── QUICKSTART.md                      # vibe-coder onboarding
│   ├── TODO.md                            # phase-keyed task list
│   └── SAFETY.md                          # what every template ships with by default
├── kaos_ui/
│   ├── __init__.py                        # public API: scaffold, list_templates, register_kaos_ui_tools
│   ├── __main__.py                        # `python -m kaos_ui` → cli.main()
│   ├── _version.py
│   ├── py.typed
│   ├── cli.py                             # `kaos-ui new|list|doctor|upgrade|info`
│   ├── manifest.py                        # TemplateManifest registry (kind → metadata)
│   ├── scaffolder.py                      # template materialization (lifted from kaos-mcp)
│   ├── post_install.py                    # uv sync, pnpm install, git init, pre-commit install
│   ├── doctor.py                          # health-check a scaffolded project
│   ├── settings.py                        # KaosUISettings(ModuleSettings)
│   ├── exceptions.py                      # KaosUIError + subclasses
│   ├── runtime.py                         # register_kaos_ui_tools(runtime)
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── tools.py                       # KaosUIListTemplates, KaosUIScaffold, KaosUIDoctor, KaosUITemplateInfo
│   ├── templates/
│   │   ├── tui/textual/                   # Textual TUI scaffold
│   │   ├── desktop/tauri/                 # Tauri desktop (preferred)
│   │   ├── desktop/pywebview/             # PyWebView desktop (Python-only fallback)
│   │   ├── web/spa/                       # Vite + React + TanStack + Tailwind + shadcn
│   │   ├── web/api/                       # FastAPI backend (was kaos-mcp/templates/api)
│   │   └── dashboard/streamlit/           # Streamlit multipage
│   └── docker/
│       └── shared/                        # base compose fragments + Caddyfile shared by web/dashboard templates
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_manifest.py
    │   ├── test_scaffolder.py
    │   ├── test_settings.py
    │   ├── test_doctor.py
    │   └── test_post_install.py
    └── integration/
        ├── test_scaffold_tui.py            # scaffold → uv sync → smoke test
        ├── test_scaffold_desktop.py        # scaffold → install → cargo build (Tauri only on dev box)
        ├── test_scaffold_web.py            # scaffold → pnpm install → vite build
        ├── test_scaffold_dashboard.py      # scaffold → uv sync → streamlit run --headless smoke
        ├── test_scaffold_api.py            # scaffold → uv sync → fastapi dev healthcheck
        ├── test_mcp_tools_in_memory.py     # exercise tools through KaosRuntime, no MCP transport
        └── test_mcp_tools_streamable.py    # exercise tools over kaos-mcp streamable HTTP
```

---

## 6. Phases

### Phase 0 — Lift and Shift (this PR)

Goal: stand the package up, write the docs, keep current `kaos new` behavior unchanged.

**Tasks**

1. Create `kaos-ui/` with `pyproject.toml`, `README.md`, `CLAUDE.md`, `docs/PLAN.md` (this), `docs/PRD.md`, `docs/QUICKSTART.md`, `docs/TODO.md`, `docs/SAFETY.md`.
2. Create `kaos_ui/` skeleton: `__init__.py`, `__main__.py`, `_version.py`, `py.typed`, `cli.py`, `manifest.py`, `scaffolder.py`, `post_install.py`, `doctor.py`, `settings.py`, `exceptions.py`, `runtime.py`, `mcp/{__init__.py,tools.py}`. Stubs only where Phase 1+ fills in real behavior.
3. Move `kaos-mcp/kaos_mcp/management/templates/{api,app,dashboard}` → `kaos-ui/kaos_ui/templates/{web/api,web/spa,dashboard/streamlit}`. The `app/` template currently mixes a SPA (`apps/spa`) and an SSR variant (`apps/ssr`) plus a `backend/` and a shared `packages/ui` — keep the existing layout intact during the move so `--ssr` selection still works. The Caddyfile and docker-compose come along.
4. Port `scaffold.py` → `kaos_ui/scaffolder.py`. Same public surface (`scaffold`, `list_templates`, `TEMPLATES` registry) so callers keep working. Wrap exceptions in `KaosUIError` subclasses.
5. Replace `kaos-mcp/kaos_mcp/management/scaffold.py` with a deprecation shim:
   ```python
   from kaos_ui.scaffolder import scaffold, list_templates, TEMPLATES  # re-export
   ```
   `kaos-mcp/kaos_mcp/management/cli.py` keeps importing from this path; behavior is identical to today.
6. Add `kaos-ui` to `kaos-mcp/[project.dependencies]` and as an editable workspace entry under `[tool.uv.sources]`. The umbrella `kaos new` CLI delegates to `kaos_ui.scaffolder`, so kaos-ui is now a runtime dep of kaos-mcp. (Direction: kaos-mcp → kaos-ui. The reverse is forbidden — see [§4.2](#42-kaos-mcp).)
7. Decide on `module/` and `workflow/` templates — see [§10 Open Questions](#10-open-questions). Default to leaving them in `kaos-mcp/kaos_mcp/management/templates/` for Phase 0 since neither is a UI; revisit in Phase 3.

**QA gate (Phase 0)**

- `cd kaos-ui && uv sync && ruff format kaos_ui/ tests/ && ruff check --fix kaos_ui/ tests/ && ty check kaos_ui/ tests/ && pytest tests/ -v` — clean.
- `cd kaos-mcp && pytest tests/` — no regressions; existing scaffold tests still pass through the shim.
- `kaos new app demo-app --dry-run` — produces the same file list as before.
- `kaos-ui new app demo-app --dry-run` — produces the same file list (parity check between the two CLIs).
- Docs land: `kaos-ui/docs/PLAN.md`, `PRD.md`, `QUICKSTART.md`, `TODO.md`, `SAFETY.md`.
- Commit gate: 8 SDLC checklists from `docs/python/checklists/` (01 research → 07 commit) — all applied.

### Phase 1 — Three Templates to 100% (revised scope)

Goal: bring three templates — `dashboard:streamlit`, `tui:textual`, `web:spa` (fullstack) — to a state where a vibe coder can scaffold and ship safely. Desktop (Tauri / PyWebView), `web:api` standalone, and SSR variants are deferred to Phase 4.

Each template, when "100% done," satisfies all of these:

1. **Scaffold→install→build→smoke** integration test green in CI (`tests/integration/test_scaffold_<kind>.py`).
2. **SAFETY contract met** (see `docs/SAFETY.md`).
3. **Uniform `Makefile` verbs** — `install dev test up down doctor build typecheck`.
4. **Doctor returns clean** immediately after `make install` on a fresh scaffold.
5. **Per-template `CLAUDE.md` + `AGENTS.md`** finalized; agent-affordances enumerated.
6. **Security scans clean** — `gitleaks` on the template, `trivy` on the generated Dockerfile.
7. **One real agent run logged** in `tests/integration/manual-agent-runs.md`.

**Detailed specs live in `docs/templates/*.md`:**

- `docs/templates/streamlit.md` — `dashboard:streamlit`
- `docs/templates/textual.md` — `tui:textual`
- `docs/templates/spa.md` — `web:spa` (fullstack)
- `docs/INTEGRATION.md` — cross-cutting "built on kaos-core" pattern, settings/auth/logging/error contracts, file-upload + DB defaults

**Sequencing**

1. **`dashboard:streamlit`** first — smallest blast radius, establishes the safety/Makefile/Dockerfile/pre-commit pattern that the other two reuse.
2. **`tui:textual`** next — net-new template, small surface, cements the pattern.
3. **`web:spa`** last — biggest of the three; benefits from the patterns the first two establish. Frontend already exists from Phase 0 lift-and-shift; backend is built fresh on `kaos-core`.

**Decisions to settle inside Phase 1**

- TypeScript lint/format: **Biome** (recommended — single tool, faster) vs ESLint+Prettier. Affects only the SPA template.
- LLM model defaults: stick with `claude-haiku-4-5` per the verified test_live.py, or switch templates' default to a configurable `APP_LLM_MODEL` (recommended) so the agent can pick.
- Auth swap-path docs: written into each template's `CLAUDE.md` for swapping bearer→OAuth/OIDC at production deploy time.

**QA gate (Phase 1)**

- All Phase 0 gates still pass.
- Three new integration tests, each scaffolds → installs → runs the scaffolded app's own smoke test.
- All three templates pass `gitleaks` scan.
- All three Dockerfiles pass `trivy` with no high/critical findings against the pinned base image.
- `./scripts/validate-platform.sh --profile ubuntu-26.04 --include-network --include-live` passes — live tier is on because the SPA chat happy-path actually hits an LLM provider.
- 13 SDLC checklists applied per change.

### Phase 2 — MCP Automation Surface

Goal: the agent can drive the full scaffolding lifecycle without shell access.

**Tasks**

1. Implement four `KaosTool` subclasses in `kaos_ui/mcp/tools.py`:
   - **`kaos-ui-list-templates`** — `ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)`. Returns the manifest registry: kind, description, required env vars, post-install commands, default ports, language stack.
   - **`kaos-ui-template-info`** — `ToolAnnotations(readOnlyHint=True, ...)`. Per-kind detail: file count, dependencies, security posture, what-not-to-touch list (mirrored from the template's `CLAUDE.md`).
   - **`kaos-ui-scaffold`** — `ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)`. Inputs: `kind` (enum constrained), `name` (slug), `target_dir` (optional path), `dry_run` (bool), `with_agent_backend` (bool). Returns `ToolResult` with a manifest (file list + target dir + next-steps), never inline file contents — see `docs/guides/mcp-data-flow.md`.
   - **`kaos-ui-doctor`** — `ToolAnnotations(readOnlyHint=True, ...)`. Inputs: `path` (defaults to cwd). Returns structured findings: deps installed, env file present, ports in expected ranges, smoke test status. Findings are agent-friendly: each issue has `what`, `how_to_fix`, and `alternative_tool` keys.
2. `register_kaos_ui_tools(runtime)` in `kaos_ui/runtime.py`. Same shape as `register_reference_tools` in kaos-reference.
3. `kaos-mcp serve --module ui` autoloads via `kaos_ui.register_kaos_ui_tools(runtime)`. Add `"ui"` to the autoload list in `kaos-mcp/kaos_mcp/management/cli.py:_cmd_serve`.
4. Implement `kaos-ui doctor` as a CLI that wires through to the same `doctor.py` used by the MCP tool — single source of truth for health checks.
5. Update `docs/architecture.md` to add kaos-ui to the dependency diagram and tool-distribution table.

**QA gate (Phase 2)**

- All previous gates.
- `tests/integration/test_mcp_tools_in_memory.py` — exercises every tool through a `KaosRuntime` directly.
- `tests/integration/test_mcp_tools_streamable.py` — exercises every tool through a real `kaos-mcp` streamable HTTP server (same pattern as `kaos-reference/tests/integration/test_mcp_streamable.py`).
- Tool-design checklist: every tool has `ToolAnnotations` set, error messages have what/how/alternative, names match `^[a-z0-9]+(?:-[a-z0-9]+){2,}$`, inputs are flat with `ParameterSchema`, dry-run produces a manifest under 16 KB (inline tier).
- Live agent test: a Codex or Claude Code session calls `kaos-ui-list-templates` then `kaos-ui-scaffold` and produces a working app. Documented in `tests/integration/manual-agent-runs.md`.

### Phase 3 — Vibe-Coder Hardening

Goal: a non-developer driving an LLM agent can scaffold a production-grade app and not get burned by missing auth, leaked secrets, broken Docker, or unsafe defaults.

**Tasks**

1. **`docs/SAFETY.md`** — the canonical statement of what every template ships with. Phase 0 stubs this; Phase 3 finishes it. See [§8](#8-the-safe-by-default-contract) for the contract.
2. **Per-template `CLAUDE.md` and `AGENTS.md`** — the agent reading these knows: which files to never touch (lockfiles, generated migrations), how to add a new route, where secrets go, how to add an env var, when to run `kaos-ui doctor`.
3. **Security review pre-commit hook** for generated projects — runs `ruff check`, `pip-audit` / `npm audit`, `gitleaks`. Pre-wired in each template's `pre-commit-config.yaml`.
4. **Production Dockerfiles** — multi-stage, non-root user (`uid=1000`), slim base image, healthcheck, no secrets baked in, build args for version pinning. Caddy reverse proxy with TLS-by-default config. Same shape across web/api and dashboard templates.
5. **`.env.example` + a hard `start` failure if `.env` is missing** — generated apps refuse to start without a configured env. No silent defaults for secrets.
6. **`kaos-ui upgrade`** — re-applies the latest template skeleton on top of an existing scaffolded project, three-way merging non-conflicting changes and surfacing conflicts with `git diff`-style hunks. Phase 3 ships the dry-run mode; full apply mode is Phase 3.5.
7. **End-to-end vibe-coder walkthrough** — `docs/oss/` gets a guide that walks a non-developer from `kaos doctor` through `kaos-ui new web myapp --with-agent-backend` through `make up` through `make doctor` to a deployed Docker container.

**QA gate (Phase 3)**

- All previous gates.
- `gitleaks` scan on every template returns clean.
- `trivy` (or `grype`) scan on each generated Dockerfile produces no high/critical CVEs against the pinned base.
- The vibe-coder walkthrough has been executed end-to-end by someone outside the engineering team. Issues filed before merging.
- Checklist 11 (`retrieval-and-evaluation`) and 12 (`benchmarking`) skipped (not applicable). Checklists 06 (review), 07 (commit), 10 (document) re-applied.

### Phase 4 — Polish (post-1.0)

Out of scope for the initial cut, captured here so they don't get lost:

- **Agent backend toggle** for the dashboard template (currently the toggle is web-only).
- **Desktop templates** — Tauri (preferred) + PyWebView (Python-only fallback). Deferred from Phase 1 because the three Phase-1 templates already cover ~95% of the vibe-coder demand and a Rust toolchain is a meaningful prerequisite to ask of users.
- **`web:api` standalone** — headless FastAPI without a frontend. Useful for "I need a backend my own SPA will call" but the fullstack `web:spa` covers the common case.
- **`web:fullstack-ssr`** — TanStack Start SSR variant of the SPA. The pre-Phase-0 `app/apps/ssr/` directory is parked.
- **Agent backend toggle** for the Streamlit template (currently the toggle is web-only).
- **Marimo template** as a fifth dashboard option.
- **Next.js SSR** template promoted from the parked `app/apps/ssr` variant into a first-class `web:next` kind.
- **Template registry** — pull custom templates from a git URL or registry, à la `cookiecutter`.
- **`kaos-ui upgrade` apply mode** — actually performs the three-way merge instead of just reporting conflicts.
- **Per-cloud deploy recipes** — `make deploy:fly`, `make deploy:railway`, `make deploy:k8s`. Out of scope for kaos-ui core; lives in template-level `Makefile`s and a docs guide.

---

## 7. Testing & QA Strategy

### 7.1 Unit (`tests/unit/`)

Fast, no I/O beyond temp dirs. Cover:

- `manifest.py` — registry shape, kind validation, lookup behavior.
- `scaffolder.py` — slugification, variable substitution, exclude prefixes, dry-run output.
- `settings.py` — env-var resolution, secret redaction, per-context overrides.
- `doctor.py` — finding shape, agent-friendly error structure.
- `post_install.py` — command construction (mock `subprocess`); the actual install runs in integration.

### 7.2 Integration (`tests/integration/`)

The acceptance gate. Every template gets a `test_scaffold_<kind>.py` that runs the full chain:

```
scaffold(kind="<kind>", name="demo-<kind>", target_dir=tmp_path)
→ post_install(target_dir)             # uv sync / pnpm install / cargo build
→ subprocess: make doctor              # template's own doctor
→ subprocess: make test                # template's own smoke test
→ assert exit code == 0
```

Tests are marked with `pytest.mark.integration`. Heavy tests (Tauri build, Docker compose up) get the `slow` marker and run only with `--runslow`.

### 7.3 MCP integration

Two layers, mirroring `kaos-reference`:

- **In-memory** — instantiate `KaosRuntime`, register tools, call them directly. No transport, no FastMCP. Fast, used in CI.
- **Streamable HTTP** — boot `kaos-mcp` with `kaos_ui` autoloaded, exercise the tools over a real MCP client session. Catches schema-export, annotation-passthrough, and `_meta.kaos_config` regressions.

### 7.4 Live tier

`./scripts/validate-platform.sh --profile ubuntu-26.04 --include-network --include-live` is the acceptance gate per `CLAUDE.md` and `docs/guides/platform-validation.md`. The `--include-live` tier matters for kaos-ui specifically when:

- Templates pull packages from PyPI / npm at install time (`--include-network`).
- Generated apps (web template with `--with-agent-backend`) can hit a real LLM provider (`--include-live`).

### 7.5 Manual agent runs

`tests/integration/manual-agent-runs.md` records sessions where a real agent (Claude Code, Codex) drove `kaos-ui-list-templates` → `kaos-ui-scaffold` → `kaos-ui-doctor` and produced a working app. These are not automated, but they are the truth check for "does an agent actually find this useable?"

### 7.6 Performance

Scaffolding should complete in under 5 seconds for any template (excluding network-bound `pnpm install`). A regression test in `tests/unit/test_scaffolder.py` asserts dry-run for the heaviest template (`web:spa`) returns under 1 second.

### 7.7 Security review

Phase 3 ships:

- `gitleaks` on the templates dir (catch placeholder secrets).
- `trivy` / `grype` on generated Dockerfiles.
- A live security review of one scaffolded `web:spa` app per release.

---

## 8. The "Safe by Default" Contract

Every template, regardless of kind, ships with the same set of guarantees so the agentic workflow has a known shape to operate inside. Phase 0 stubs `docs/SAFETY.md`; Phase 3 finishes it. Summary:

| Guarantee | What it means |
|---|---|
| **Auth-ready** | Every web/api/dashboard template wires `kaos-agents` permissions or a stubbed JWT bearer. No anonymous endpoints by default. |
| **Secrets hygiene** | `.env.example` enumerates every secret. Loader refuses to start if `.env` is missing. `.gitignore` covers `.env`, `.env.local`, build outputs, OS junk. No secrets in env-vars, args, or Dockerfile. |
| **CSP + CORS locked** | Web templates ship a strict Content-Security-Policy (no `unsafe-inline`, no `unsafe-eval`), CORS allowlist not `*`, secure cookies (`HttpOnly`, `SameSite=Lax`, `Secure` in prod). |
| **No DEBUG in prod** | `DEBUG`/`development` flags are unreachable in the prod build path. Pydantic settings refuse to load with `DEBUG=True` when `ENV=production`. |
| **Container hardened** | Multi-stage Dockerfile, non-root user, slim base, healthcheck, build-arg version pin, no secrets baked in. |
| **Pre-commit guard** | `pre-commit-config.yaml` runs ruff, ty, eslint, and `gitleaks` on every commit. |
| **Doctor-clean on scaffold** | `make doctor` exits 0 immediately after `make install` on a fresh scaffold. If it doesn't, the template is broken. |
| **Agent guardrails** | Each template has its own `CLAUDE.md` listing files-not-to-touch (lockfiles, generated routes, migration files), where to add new code, and which `make` targets to use. |

---

## 9. CLI Surface

Per `docs/guides/cli-standard.md`. Every command supports `--json` with the standard envelope.

### `kaos-ui`

```
kaos-ui list                                  # list available kinds
kaos-ui info <kind>                           # detail on one kind (deps, env, ports)
kaos-ui new <kind> <name> [options]           # scaffold
kaos-ui doctor [path]                         # health-check a scaffolded project
kaos-ui upgrade [path] [--dry-run]            # re-apply skeleton (Phase 3)
```

`new` options:

- `--target DIR` — target directory (default: `./<name>`).
- `--dry-run` — list files that would be created; no writes.
- `--ssr` (web kind only) — use TanStack Start (SSR) instead of SPA.
- `--with-agent-backend` — wire `kaos-agents` into the generated backend.
- `--kind <subkind>` (desktop kind only) — `tauri` or `pywebview`.
- `--no-git` — skip `git init`.
- `--no-install` — skip post-install (`uv sync` / `pnpm install`).

JSON envelopes:

```jsonc
// kaos-ui list
{"command": "list", "templates": [{"kind": "web:spa", "description": "...", "stack": "..."}, ...]}

// kaos-ui new
{"command": "new", "kind": "web:spa", "name": "demo", "target": "/path/to/demo",
 "files": ["..."], "post_install": ["pnpm install"], "next_steps": ["cd demo", "make dev"]}

// kaos-ui doctor
{"command": "doctor", "path": "/path/to/demo", "ok": false,
 "findings": [{"severity": "error", "what": "...", "how_to_fix": "...", "alternative_tool": null}]}
```

### Unified `kaos`

`kaos new` continues to delegate. Once the umbrella CLI is moved out of `kaos-mcp` ([Open Question 1](#10-open-questions)), kaos-ui registers as a subcommand provider via entry-points.

---

## 10. Open Questions

These are flagged decisions that affect Phase 1+ scope. Phase 0 lands without them; Phase 1 cannot start until they're settled.

1. **Where does the umbrella `kaos` CLI live?** Currently `kaos-mcp/kaos_mcp/management/cli.py`. Two options: (a) move to `kaos-core` as a thin subcommand dispatcher; (b) extract to a new `kaos-cli` package. Recommendation: (a) — kaos-core sits at the bottom of every dependency chain and an umbrella console script there does not introduce new coupling.
2. **Desktop framework — Tauri or PyWebView as primary?** Tauri is smaller/safer but adds Rust toolchain to the vibe coder's path. PyWebView is Python-only. Recommendation: ship both, default to Tauri, fall back to PyWebView when Rust is not available. Detected by `kaos-ui doctor`.
3. **Where do `module/` and `workflow/` templates live?** They are not UIs. Options: (a) leave in `kaos-mcp/kaos_mcp/management/templates/` indefinitely; (b) move `module/` near `kaos-reference` (which is itself a module-author example); (c) move `workflow/` near `kaos-agents` (which owns the agent runtime). Recommendation: defer past Phase 0.
4. **Should `kaos-ui` itself depend on `kaos-mcp`?** No. The MCP integration is via `KaosTool` subclasses registered onto `KaosRuntime`. `kaos-mcp` imports `kaos_ui` (when `--module ui` is passed), not the other way around. This keeps `kaos-ui` installable by anyone who only wants the CLI scaffolder.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Templates rot — break silently as upstream packages bump major versions | Integration tests run scaffold→install→build for every kind on every CI run. Pinned major versions in `pyproject.toml.tmpl` / `package.json` |
| Vibe coder's agent edits files outside the safe set and breaks things | Per-template `CLAUDE.md` lists never-edit files. `kaos-ui doctor` flags unexpected modifications to generated files. Pre-commit hooks catch obvious mistakes |
| Two scaffolders drift (kaos-ui standalone CLI vs `kaos new` shim) | Single source of truth in `kaos_ui.scaffolder`. The shim in kaos-mcp is one line. Parity test in `tests/integration/test_kaos_new_parity.py` |
| Tauri toolchain breaks on a vibe coder's machine | `kaos-ui doctor` runs `cargo --version` and falls back to PyWebView template suggestion. Tauri is opt-in, not default for desktop kind |
| Templates leak secrets into git history (placeholder API keys, dev tokens) | `gitleaks` in pre-commit hook. CI gate scans templates for any `sk-`, `ghp_`, `xoxb-` patterns |
| Generated apps exposed insecurely (default 0.0.0.0 bind, no auth) | Templates default to `127.0.0.1` and require `--host 0.0.0.0` flag. Auth wired by default; anonymous endpoints require explicit opt-in |

---

## 12. Definition of Done (per phase)

- **Phase 0:** package exists, docs exist, `kaos new` keeps working through the shim, both QA suites green.
- **Phase 1:** TUI + desktop templates ship, integration tests for all kinds green.
- **Phase 2:** four MCP tools live, `kaos-mcp serve --module ui` works, agent can drive the full lifecycle.
- **Phase 3:** SAFETY.md complete, every template passes `gitleaks` and a Dockerfile vuln scan, end-to-end vibe-coder walkthrough executed by someone outside the team.
- **Phase 4:** post-1.0 features as warranted.
