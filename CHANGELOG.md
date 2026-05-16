# Changelog

All notable changes to `kaos-ui` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0a6] — 2026-05-16

### Added — Typography + spacing + tabular polish (Round 2)

This release focuses entirely on visual polish across the SPA. A
research pass surveyed Linear, Notion, iA Writer, Bear, Pages, Word,
Anthropic console, ChatGPT, Perplexity, Stripe Dashboard, and shadcn
to land on a coherent type scale, spacing rhythm, and tabular
primitive. The full audit is in
`.screenshots/RESEARCH-typography.md`.

**Type scale + density tokens.** Added explicit
`--text-2xs` / `xs` / `sm` / `base` / `md` / `lg` / `xl` / `2xl` /
`3xl` to `examples/single-user-chat/packages/ui/src/styles/globals.css`,
each with its own paired `--text-*--line-height`. The load-bearing
decision: **chat-body text anchors at 16px / 1.65** for reading-flow
surfaces (matches Anthropic console + iA Writer + Bear baseline) while
**UI chrome stays at 13px** (Linear / Notion sidebar baseline). Plus
four named density tokens — `compact` / `default` / `comfortable` /
`spacious` — for row-height consistency across data surfaces.

**`<DataTable>` primitive** (`packages/kaos-ui-react/src/data/DataTable.tsx`).
Generic tabular component for `kaos-tabular` summaries, document
comparison grids, citation tables, and any rectangular data surface
the agent exposes inside the chat. Features:

- Three density tiers wired to the new density tokens.
- Typed cells: `text` / `number` / `currency` / `percent` / `date` /
  `code` / `badge` / `link` / `custom`, each with right alignment +
  formatting + monospace pairing defaults.
- Sticky header.
- Sortable headers (uncontrolled by default; `sortBy` + `onSortChange`
  for controlled mode).
- Semantic `<table>` + `<caption>` + `scope` + `aria-sort` markup.
- Hairline borders, no zebra fills — Linear / Stripe Dashboard register
  rather than Material grid.

Exported from `@273v/kaos-ui-react/chat` as
`DataTable` + `Column` + `ColumnKind` + `DataTableDensity` +
`DataTableProps`.

**Markdown body polish.** `.kaos-md` in
`packages/kaos-ui-react/src/theme/tokens.css` rewritten end-to-end:

- 16 px / 1.65 body anchored on the new scale.
- Heading rhythm tightened (smaller h1/h2/h3 sit *within* the message
  block instead of shouting like blog headers).
- Inline `code` gets a hairline border + subtle background.
- `pre` code blocks get hairline-only treatment (no inverted dark
  panel — research recommendation: keep code surface = panel surface
  for the "serious document" register).
- Blockquotes get a left rule, muted body, no italic.
- Tables get hairline rules, header weight, generous padding.
- Links carry a hairline underline that brightens on hover; underline
  always present for a11y.
- Adds `text-wrap: pretty` for better last-line orphan handling.

**Component-level type & spacing fixes:**

- Chat header gets a serif title (matches Welcome + Login hero) and
  monospace model name in the subtitle.
- Composer textarea bumped to 72 px min-height + 15 px body + 1.55
  line-height + rounded-lg corners + a 36 px send button. Reads like
  a draft surface, not a settings input.
- Message component uses 24 px vertical padding (was 16 px), with the
  YOU / ASSISTANT label set in 11 px tracked uppercase at 70 %
  opacity. Assistant turns get the `.kaos-md` editorial body
  treatment; user / tool / error turns stay at 15 px chrome.
- Sidebar rows tightened to 32 px with a `before:` accent stripe on
  the active row (matches UX-LANGUAGE.md §4.6).
- Time-bucket headers (Today / Yesterday / …) bumped to 70 %
  foreground at 10 px tracked uppercase — uniform with the message
  role labels.

### Fixed

- a11y: chat-header subtitle had 3.99:1 contrast at
  `text-foreground/55`; bumped to `/70` for 4.5:1+ AA compliance.
- a11y: sidebar time-bucket header same regression — held at `/70`.

### Verification

- Lighthouse on the active chat surface: **100 / 100 / 100 / 100**
  (a11y / best-practices / SEO / agentic). 36 audits passed, 0 failed.
- Browser console: clean.
- 96 SPA vitest, 118 root kaos-ui pytest — no regressions.

## [0.1.0a5] — 2026-05-16

### Added — UX overhaul (Round 1)

After the 0.1.0a4 audit shipped, a follow-up round captured 14
screenshots across every SPA surface and ran the work back through
the kaos-modules competitive analysis (`Harvey`, `Legora`, `Mike`,
`Casetext`, `Lexis+ Protégé`) and a fresh web SOTA scan (`Claude`,
`ChatGPT` Oct-2025, `Perplexity`, `Cursor`, `v0`). The findings are
captured in `.screenshots/AUDIT.md`. This release lands the
high-impact items that close the gap to the SOTA chat-UI baseline.

- **Welcome page rebuilt as a capability grid.** Replaces the bare
  "Welcome." heading with a 4-card grid (Search FR / Summarize
  document / Draft or redline / Verify citation) that creates a
  fresh session and prefills the composer in one click — the
  dominant pattern across ChatGPT / Gemini / Cursor in 2025-2026.
  Persona chips (research / drafting / forensics) sit below the
  grid; picking one creates the session with that policy preset.
  (`apps/spa/src/routes/_auth.sessions.index.tsx`)
- **Sidebar time-bucketing.** Sessions are now grouped by
  `last_message_at`: Today / Yesterday / Previous 7 days /
  Previous 30 days / Older. OpenAI removed the same grouping in
  June 2025 and faced a user revolt — the strongest signal in the
  SOTA research. Buckets only render under the default "Last used"
  sort; explicit user sorts ("Created", "Starred first") stay flat.
  (`apps/spa/src/components/sessions/SessionList.tsx`)
- **`/sessions/:id?prefill=…` route param.** Capability cards on
  the Welcome page set it, the chat route reads it on mount and
  clears it from the URL via `replace`, so a refresh doesn't
  re-prefill and the URL stays scannable.

### Fixed

- **High: SettingsSheet hooks-order violation.** Opening the sheet
  threw `Rendered more hooks than during the previous render`
  because two `useMemo` calls lived below an
  `if (!open) return null` early return. Moved the hooks above the
  early return so they always run in the same order.
  (`apps/spa/src/components/settings/SettingsSheet.tsx`)
- **a11y: 4 form fields missing `id`/`name`.** Sidebar sort
  `<select>`, composer model `<select>`, composer file `<input>`,
  composer message `<textarea>` all had aria-labels but no
  id/name, which Chrome flagged + which broke form-reset
  heuristics. Added stable id/name on each.
  (`apps/spa/src/components/sessions/SessionList.tsx`,
  `packages/kaos-ui-react/src/chat/ModelPicker.tsx`,
  `packages/kaos-ui-react/src/chat/Composer.tsx`)
- **a11y: WCAG 2.5.3 Label-in-Name on the Citations header
  button.** The accessible name was "Toggle citations panel" but
  the visible badge text was "4". Aria-label is now
  ``Citations (${count})`` when a count is present.
  (`apps/spa/src/routes/_auth.sessions.$id.tsx`)
- **a11y: 4.06:1 contrast on the sidebar session-row message-count
  badges.** Below WCAG AA 4.5:1. Bumped from
  `text-muted-foreground/15` / `text-muted-foreground` to
  `text-muted-foreground/20` / `text-foreground/80`.
  (`apps/spa/src/components/sessions/SessionListItem.tsx`)
- **a11y: login form lacked a username field.** A `type="password"`
  bearer field without a preceding username breaks password-manager
  autofill and weakens screen-reader form semantics. Added a hidden
  `autocomplete="username"` text input before the password field.
  (`apps/spa/src/routes/login.tsx`)
- **SEO + crawler hygiene.** Added a `<meta name="description">` to
  `index.html`, a `public/robots.txt` that disallows all
  (single-tenant auth-gated app), and a `public/llms.txt` that
  declares the project shape for LLM crawlers. Lifts Lighthouse SEO
  from 60 → 100 and Agentic-Browsing from 50 → 100.
- **Lighthouse accessibility 96 → 100** after the contrast +
  Label-in-Name + form-field fixes land together.

### Verification

- Lighthouse on the active chat surface: **Accessibility 100 / Best
  Practices 100 / SEO 100 / Agentic-Browsing 100** — 36 audits
  passed, 0 failed.
- Browser console: clean across `/login`, `/sessions`, and
  `/sessions/:id` after the fixes; no application errors, no
  warnings, no DevTools `[issue]` lines.
- Backend pytest: 144 passing (no regressions).
- SPA vitest: 96 passing (no regressions).
- Root kaos-ui pytest: 118 passing (no regressions).

## [0.1.0a4] — 2026-05-15

### Fixed — Post-0.1.0a3 audit (7 findings)

External audit on `v0.1.0a3` caught seven issues; this hotfix
closes all of them with regression tests.

- **(High) Generated `web:spa` production proxy was broken.** The
  template `Caddyfile` used `handle_path /v1/*`, which strips `/v1`
  before forwarding, so every `/v1/...` backend route 404'd behind
  Caddy. Changed to `handle /v1/*` to match the working single-user
  example.
  (`kaos_ui/templates/web/spa/Caddyfile`)
- **(High) Transcript leak on session switch mid-stream.** The
  `useSendMessage` reset effect skipped abort/reset whenever a
  stream was in flight, even when the user navigated to a different
  session. Result: session A's stream + transcript bled into the
  session B view. Fixed by tracking the last hydrated `sessionId`
  in a ref — same-session refetches still no-op, but a session
  change always tears down the old stream.
  (`packages/kaos-ui-react/src/hooks/use-send-message.ts`)
- **(High) CapabilityApproval card had no resume path.** The
  reducer kept the turn `pending` on `capability_requested`, but
  the SPA route rendered `<Message>` without an `onCapabilityDecide`
  handler, so the approval buttons disabled themselves. Wired the
  decide handler in the chat route + added `onPinElevationToSession`
  so the "Pin to session" affordance on `<ElevationPill>` works
  end-to-end. Decisions resolve through
  `PATCH /v1/chat/sessions/:id/tool-set` for "Enable for session" /
  "Pin to session"; the other three cleanly dismiss.
  (`examples/single-user-chat/apps/spa/src/routes/_auth.sessions.$id.tsx`)
- **(Medium) Document downloads bypassed bearer auth.** The
  `<DocumentExplorer>` component used a plain `<a href>` for the
  Download icon, which doesn't attach `Authorization` headers, so
  the request 401'd against the example's bearer-token middleware.
  Added an `onDownload` prop that lets the host do an authenticated
  fetch → blob → save flow; the legacy `getDownloadUrl` is
  preserved for cookie-auth consumers and marked deprecated in the
  JSDoc. The example route now uses `onDownload` with `apiFetch`.
  (`packages/kaos-ui-react/src/chat/DocumentExplorer.tsx`,
  `examples/single-user-chat/apps/spa/src/routes/_auth.sessions.$id.tsx`)
- **(Medium) `denied_tools` recursion floor could be lost.**
  Creating a session with `tools_enabled=False` wrote
  `denied_tools=[]`; a later `PATCH /tool-set` from the settings
  sheet preserved the empty list. The four self-recursive
  `kaos-agent-*` tools could re-enter the allow set when the user
  flipped tools back on. Added `with_denied_floor()` to
  `app.models` and called it from every persistence path that
  writes a `SessionPolicyWire`. Three regression tests pin the
  invariant.
  (`examples/single-user-chat/backend/app/models.py`,
  `examples/single-user-chat/backend/app/persistence/sessions.py`)
- **(Medium) Template upload buffered full bodies before size check.**
  `uploads.py.tmpl` called `await file.read()` before delegating
  to `validate()` for the size cap. Caddy enforces the cap at the
  proxy edge, but direct hits on uvicorn / dev / an alternate
  proxy could exhaust memory. Refactored to a streamed chunk loop
  that short-circuits at 256 KiB increments and returns 413 as
  soon as the cap is exceeded. Updated the template's oversize
  test accordingly.
  (`kaos_ui/templates/web/spa/backend/app/routers/uploads.py.tmpl`,
  `kaos_ui/templates/web/spa/backend/tests/test_uploads.py.tmpl`)
- **(Medium) Backend `ty` gate had 16 stale diagnostics.** Cleaned
  up `_to_sse_event`'s narrowed return type (`cast` rather than
  blanket ignore), tightened `_effective_tool_set` to use
  `SessionToolSetWire` instead of `object`, tagged
  `summarize_session_title`'s `@llm_call` empty body, defensively
  walked `hit.document` in `corpus_search`, typed
  `ToolCallRecord.status` as the canonical three-way Literal, and
  migrated three test fixtures off the legacy
  `tools_enabled=` SessionMeta kwarg pattern onto
  `policy=SessionPolicyWire.for_persona(...)`.

## [0.1.0a3] — 2026-05-15

### Added — AgenticLoop wire-up (kaos-agents 0.1.0a4)

The single-user-chat example now drives every turn through the
`run_agentic_turn` orchestrator. The user-visible win: **the agent no
longer "gives up" because a relevant tool group (e.g. web) is missing
from `allowed_groups`** — the per-iteration planner detects the gap,
the loop auto-elevates green-auto groups within the session's
`soft_ceiling`, and the turn resumes with the right tools. The
canonical regression test
[`test_agent_never_gives_up_on_searchable_question`](./examples/single-user-chat/backend/tests/integration/test_no_giveup.py)
pins this behavior against live `claude-haiku-4-5`.

- **`SessionPolicyWire`** (`backend/app/models.py`) — new wire shape
  carrying the two-tier ceiling (`allowed_groups` + `soft_ceiling`),
  the three-way persona preset (`research` / `drafting` /
  `forensics`), and three independent loop limiters
  (`max_loop_iterations` / `max_loop_cost_usd` /
  `max_loop_wall_clock_seconds`). Round-trips through the canonical
  `kaos_agents.types.SessionPolicy` via `to_session_policy()`.
- **Three-state SessionMeta migration** — sidecars persisted under
  the legacy `tools_enabled: bool`, the TR-3
  `tool_set: SessionToolSetWire`, or the new
  `policy: SessionPolicyWire` shape all hydrate into the canonical
  policy. The `tool_set` field survives as a `@computed_field`
  derived from the policy for SPA back-compat.
- **`agentic_worker.make_worker`**
  (`backend/app/services/agentic_worker.py`) — adapter wrapping the
  existing `stream_chat` SSE pump into the
  `WorkerCallable` shape `run_agentic_turn` expects. Captures the
  per-turn invariants (httpx client, bearer, meta, budget, catalog,
  corpus) and exposes the per-iteration knobs (`user_message`,
  `allowed_groups`, `thinking_note`, `iteration`). The replan
  `thinking_note` is threaded into the system prompt on iteration
  2+ — NOT as a fake user message — preserving transcript hygiene.
- **Rewired `POST /v1/chat/sessions/{id}/messages`**
  (`backend/app/routers/chat.py`) — every turn now flows through
  `run_agentic_turn(policy, worker, available_groups, ...)`.
  Typed `KaosEvent` objects from the loop (`ToolPolicyElevated`,
  `CapabilityRequested`, `GoalChecked`, `LoopTerminated`) are
  serialized with the `type` discriminator injected; worker SSE
  dicts pass through verbatim.
- **Four new SSE wire types** in `kaos-ui-react`
  (`packages/kaos-ui-react/src/lib/events.ts`):
  - `tool_policy_elevated` — audit trail of green-auto elevation
  - `capability_requested` — yellow-confirm pause for user approval
  - `goal_checked` — Critic's three-way verdict (satisfied /
    needs_more_work / insufficient_evidence)
  - `loop_terminated` — always the last event; carries the
    termination reason (7 cases)
- **Four new React components** (`packages/kaos-ui-react/src/chat/`):
  - `<GoalCheckBadge>` — green/amber/gray Critic-verdict pill with
    expandable rationale + per-call cost / latency
  - `<ElevationPill>` — chip-by-chip "Auto-enabled X" badge with
    inline "Pin to session" affordance
  - `<CapabilityApproval>` — inline 4-action card for yellow-confirm
    pauses (Enable turn / Enable session / Deny+continue / Deny+stop)
  - `<LoopTerminatedBanner>` — per-reason terminal banner (silent on
    `satisfied`; info on `insufficient_evidence`; warn on the rest)
- **Backend test coverage:** +33 unit tests + 7 chat-router
  integration tests + 2 live LLM regression tests covering the
  AgenticLoop end-to-end (145 total backend tests passing).
- **SPA test coverage:** +7 vitest reducer tests for the new event
  types (96 total SPA vitest tests passing).
- **Dropped:** legacy `app/services/turn_tool_policy.py` and its
  unit + live integration tests — superseded by the canonical
  `kaos_agents.planning.policy.plan_turn_tool_policy` running
  inside the loop.

### Changed

- **Default session ceiling widened to the 8-group research persona.**
  Pre-AgenticLoop sessions opened with `{documents, citations, vfs}`
  (web opt-in). New sessions open with the research soft-ceiling
  (`{web, browser, netinfra, documents, citations, vfs, forensics,
  retrieval}`) — the per-iteration planner narrows from this set
  per-turn, so users no longer need to manually opt in to every
  group up front.
- **Removed `turn_policy_model` / `turn_policy_confidence_threshold`**
  AppSettings; replaced by `agentic_planner_model` /
  `agentic_goal_check_model` for the loop's planner + Critic
  Signatures (`backend/app/settings.py`).

## [0.1.0a2] — 2026-05-15

### Fixed

- **FIX-19 — `<DocumentExplorer>` flexbox layout.** The aside
  column grew past its declared `w-80` when a file's summary
  carried a long unbreakable token (URL, hash). Flexbox's default
  `min-width: auto` lets a child blow out the parent's width
  unless `min-w-0` overrides; added `min-w-0 overflow-hidden` to
  the aside + `break-words` to error / summary text containers.
  (`packages/kaos-ui-react/src/chat/DocumentExplorer.tsx`)
- **FIX-20 — auto-titler kwarg compat with kaos-llm-core 0.1.0a7+.**
  The 0.1.0a7 wrapper rejects unknown keyword arguments including
  the per-call `model=` override that earlier versions accepted.
  Fix: build a fresh `Call` at runtime when `APP_AUTO_TITLE_MODEL`
  differs from the decorator baseline; otherwise use the cached
  call. Restores the auto-title flow for sessions where the operator
  has overridden the title model.
  (`examples/single-user-chat/backend/app/services/title.py`)

### Added — Tool registry + dynamic per-turn policy (TR-1..TR-13)

A complete tool-policy stack covering registry, ceiling enforcement,
per-turn narrowing, and transparency. The single `tools_enabled: bool`
toggle (now derived) is superseded by a per-category ceiling + a
Haiku-class planner Program that picks the smallest set for each turn.

- **`kaos_ui.agents.register_kaos_tool_groups(runtime)`** partitions
  every registered KAOS tool into `kaos_agents` ToolGroups by name
  prefix: `web` (kaos-source-*), `documents` (kaos-pdf-*,
  kaos-office-parse-*, kaos-content-*), `citations` (kaos-citations-*),
  `vfs` (kaos-core-vfs-*, kaos-core-artifacts-*). The single-user-chat
  example calls this after every `register_*_tools` so the proxy
  filter resolves SessionToolSet against a populated registry.
- **`SessionMeta.tool_set: SessionToolSetWire`** in
  `examples/single-user-chat`. Pydantic shape:
  `{allowed_groups: list[str], denied_tools: list[str], auto_narrow:
  bool}`. Legacy meta sidecars with only `tools_enabled: bool`
  migrate at load time. Default ceiling = documents+citations+vfs;
  web is opt-in. `tools_enabled` becomes a `@computed_field` derived
  view for back-compat.
- **`GET /v1/chat/categories`** + **`PATCH /v1/chat/sessions/:id/tool-set`**
  routes in `examples/single-user-chat`. Unknown groups 422 with
  the offending names so the SPA can surface inline.
- **`TurnToolPolicy` Program** (single-user-chat,
  `app/services/turn_tool_policy.py`) runs before each tool-able turn,
  narrows the ceiling to just this message's needed groups via a
  Haiku kaos-llm-core Call. Cost ≤ $0.0002/turn, latency p95 ≤ 300ms.
  Confidence < 0.6 → falls back to ceiling. Promotes to
  `kaos_agents.planning.policy` after two release windows.
- **`tool_policy_decided` SSE event** in `@273v/kaos-ui-react`'s
  taxonomy (kaos-ui extension — not yet stock kaos-agents).
- **`<ToolPolicyBadge>`** in `@273v/kaos-ui-react/chat` renders a
  per-turn transparency chip above the assistant message with the
  planner's reasoning, confidence, cost, and latency on click.
- **`<SettingsSheet>` Tool policy section** in the single-user-chat
  SPA: per-category checkboxes + preset picker + auto-narrow toggle.
  Replaces the legacy "Enable read-only tools" single checkbox.
- **`<CostStrip>` Planner row** in `@273v/kaos-ui-react/debug`
  attributes planner cost separately when `tool_policy_decided`
  fires with non-zero cost.

Tests:
- 7 unit tests for SessionMeta migration (single-user-chat).
- 7 unit tests for the TurnToolPolicy Program (single-user-chat).
- 8 integration tests for the new HTTP routes (single-user-chat).
- 4 live integration tests for ceiling + planner end-to-end behavior
  (Anthropic-key gated, `pytest.mark.live`).
- 12 unit tests for `kaos-agents` ReAct schema-recovery (FIX-16).
- 4 vitest tests for the new SSE event in the package.
- 6 vitest tests for `<ToolPolicyBadge>`.
- 4 vitest tests for the `<CostStrip>` planner row.
- 7 vitest tests for the SettingsSheet Tool policy section.

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

[Unreleased]: https://github.com/273v/kaos-ui/compare/v0.1.0a6...HEAD
[0.1.0a6]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a6
[0.1.0a5]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a5
[0.1.0a4]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a4
[0.1.0a3]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a3
[0.1.0a2]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a2
[0.1.0a1]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a1
