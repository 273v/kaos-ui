# single-user-chat — Product Requirements

> Status: draft. Owner: kaos-ui. Last updated: 2026-05-14. Verified against PyPI installs of `kaos-agents==0.1.0a1`, `kaos-core==0.1.0a6`, `kaos-llm-client==0.1.0a3`. Reviewed against `kaos-ui/docs/PRD.md` and `kaos-ui/docs/INTEGRATION.md` for style consistency. See `UX-LANGUAGE.md` for the visual-design spec.

## 1. Problem

The `web:spa` scaffold (`kaos_ui/templates/web/spa/`) ships a single-turn chat stub. It streams `kaos-agents` events over SSE and renders user/assistant bubbles — but:

- Conversation state lives only in React state (`apps/spa/src/routes/_auth.chat.tsx:23-27`). Every page reload nukes the transcript.
- The session id is hardcoded to `"spa-default"` (`_auth.chat.tsx:58`). There is no concept of multiple conversations.
- The frontend `switch` checks 9 event-type strings but **only 4 are real wire types** as of `kaos-agents==0.1.0a1`: `text_delta`, `intent_classified`, `usage_observed`, `run_error`. The strings `turn_start`, `tool_call_start`, `tool_call_result`, `step_start`, `turn_complete` are dead branches — kaos-agents replaced that old `TurnStart`/`StepStart`/`ToolCallStart` taxonomy with a single `span` event class carrying `subject` (TURN, STEP, TOOL_CALL, PLAN, SUBAGENT, HANDOFF) + `phase` (START, PROGRESS, COMPLETE, ERROR, CANCELLED), plus a separate `turn_summary` value event. The template never updated. See `events/__init__.py` docstring: *"Replaces the old TurnStart/TurnComplete / StepStart/StepComplete / ToolCallStart/ToolCallResult / HandoffStart / SubagentStart/SubagentComplete zoo."*
- The model + system prompt are hardcoded in `backend/app/services/chat.py.tmpl:26-30, 45`. No UI controls.
- There is no `GET /v1/sessions`, no `POST /v1/sessions`, no history endpoint — only the streaming endpoint. (Note: `kaos_agents.api.server.create_app()` ships these endpoints upstream, but the template doesn't use it.)

Vibe coders see this and reasonably ask: "where's the rest of the chat app?" The answer today is: "build it yourself." That's a documentation gap, not a design choice.

This example closes the gap. It is a complete, runnable, single-user agentic chat application that demonstrates the same `packages/ui` library, the same `kaos-agents` wire, the same auth pattern, and the same SSE primitive as `web:spa` — but with the missing pieces filled in. It exists as documentation-by-code.

## 2. Audience

Two readers:

1. **The vibe coder** — clones `kaos-modules`, runs `make install && make dev` in this directory, and uses the result as the worked example they copy from. They are probably a lawyer, data scientist, or builder who knows enough Python and TypeScript to read but not necessarily to architect.
2. **An AI agent** scaffolding a similar app from scratch — reads this code as the canonical pattern for "how `kaos-agents` + a SPA fit together end-to-end."

Not a customer-facing product. Not a multi-tenant SaaS. One human, one bearer token, one local machine.

## 3. Goals

| ID | Goal | How we'll know it's met |
|----|------|-------------------------|
| G1 | **Conversation persistence.** Send a message, reload the tab, the conversation is still there. | E2E test: send → reload → assert previous messages present. |
| G2 | **Multi-session.** New-chat button, session-list sidebar, click-to-open. | E2E test: create 2 sessions → assert both visible → switch between. |
| G3 | **Full event surface.** Every `kaos-agents` event type renders something (even a debug chip). The `span` event must dispatch on `(subject, phase)`; we cover all observed subject/phase combinations explicitly. | Unit test: feed each of the 15 event classes (and the full Cartesian of `SpanSubject × SpanPhase` exercised in practice) into the renderer → assert no fall-through. |
| G4 | **Model picker.** Switch among ~6 current-generation models per session without losing the conversation. | E2E test: pick a different model → send → assert the new model name appears in the turn summary. |
| G5 | **Per-session system-prompt editor.** Edit prompt in a drawer, persist with the session. | E2E test: set custom prompt → reload → assert prompt persisted and applied on next turn. |
| G6 | **Transcript export.** Download a session as Markdown and as JSON. | Unit test: round-trip JSON export → re-import → assert message equality. |
| G7 | **Reuse `packages/ui`.** Same components, same design tokens, no fork. | Build-time check: `packages/ui` is imported as a workspace dep, not vendored. |
| G8 | **Same auth as `web:spa` — bearer token from `.env`.** v1 stores the bearer in `localStorage` for dev-mode simplicity (XSS trade-off documented in `auth/storage.ts`); Phase 4+ wraps `create_app()` with a cookie issuer so production deploys use HttpOnly+Secure+SameSite=Strict. | Code review: `backend/app/auth.py` matches the template's pattern within trivial diffs. `apps/spa/src/auth/storage.ts` carries the dev-only XSS notice. |
| G9 | **Boots in <5 minutes** for a first-time reader with a single API key. | Manual: timed walkthrough on a fresh clone. |
| G10 | **Passes the standard QA gate** — `ruff format && ruff check --fix && ty check && pytest` for Python, `biome check && tsc --noEmit && vitest run` for TS. | CI: green on every commit. |

## 4. Non-goals

Explicitly out of scope. Listed because each is the kind of thing a reviewer might reasonably propose:

- **Multi-user.** One bearer token, one cookie, one human. No user table, no per-user namespacing.
- **OIDC / SSO.** The `web:spa` template's `CLAUDE.md` documents the bearer → OIDC swap path; this example doesn't traverse it.
- **Tool-call approval UI.** `kaos-agents` exposes `ToolCallApprovalRequired` events and resume semantics (`kaos_agents/runtime/runner.py:479-550`). Wiring a "review this tool call" modal is meaningful UX work and a future example by itself.
- **RAG corpus management.** No document upload UI, no `kaos-content` ingest pipeline, no `kaos-source` retrieval flow. The chat sees no documents.
- **Agentic patterns beyond `CHAT`.** `AgentPattern.PLAN` and `AgentPattern.RESEARCH` work, but the demo locks to `CHAT` for simplicity. Switching patterns is a one-line change a reader can make.
- **Mobile-first responsive layout.** Desktop-first. Mobile is best-effort.
- **A template.** Not registered in `kaos_ui/manifest.py`. Not stamped out by `kaos-ui new`. The user clones, they don't scaffold.
- **PyPI distribution.** Not added to `[tool.hatch.build.targets.sdist] include` in v1. Lives in the git repo.
- **Cloud deployment automation.** `Caddyfile` + `docker-compose.yml` are provided as in the scaffold; pushing them to a cloud host is the reader's job.
- **A second backing store.** No SQLite, no Postgres. All persistence is JSON files in the kaos VFS namespace.

## 5. Success metrics

- **Time-to-first-message** ≤ 5 minutes from `git clone` on a fresh Ubuntu 26.04 box with Python 3.13+ and Node 24+.
- **First-delta latency** < 2 s on `anthropic:claude-haiku-4-5` from a US-East dev machine on warm import.
- **Event coverage** — 15 of 15 `kaos-agents` event types covered by a render-path unit test.
- **Documentation coverage** — every file in the example has a top-of-file docstring or block comment explaining its role.
- **CI gates green** — `ruff`, `ty`, `pytest`, `biome`, `tsc`, `vitest` all pass on every commit. Live LLM tests run against the cheapest current-generation model (`anthropic:claude-haiku-4-5`).

## 6. Constraints

- **License-clean.** No AGPL/GPL dependencies. Same constraint as every other package in this monorepo.
- **Settings discipline (per top-level `CLAUDE.md` § Configuration Hierarchy).** Backend never reads `os.environ` directly. Everything goes through `AppSettings(env_prefix="APP_")` with kaos-llm-* legacy fallbacks behind `mode="before"` validators. `SecretStr` for API keys.
- **Logging discipline.** `from kaos_core.logging import get_logger` only. No `logging.getLogger(__name__)`.
- **Auth.** Bearer token from `.env`. v1 stashes the token in browser `localStorage` for dev simplicity — this is the kaos-agents bundled-API contract (no cookie-issuing endpoint ships with kaos-agents 0.1.0a1). Phase 4+ adds a cookie wrapper around `create_app()` that exchanges the bearer for an HttpOnly+Secure+SameSite=Strict cookie so XSS can't lift the token. The trade-off is documented in `apps/spa/src/auth/storage.ts` and surfaced on the login page so a deploying operator sees it. Do not ship single-user-chat to a public-facing host in v1 without putting it behind a trusted-network gate.
- **Streaming.** `sse-starlette.EventSourceResponse` on the backend, `eventsource-parser` via `readSseStream` on the frontend. Same primitives as the template — no `EventSource`, no Server-Sent-Events polyfill, no `WebSocket`.
- **Frontend components.** Consume `packages/ui` from the web:spa template via pnpm workspace resolution. Do not fork shadcn primitives into this example.
- **Models.** Use the `provider:model` string format from `kaos-llm-client`. Default to `anthropic:claude-haiku-4-5` per `KaosAgentSettings().default_llm_model` (verified on PyPI install). The model catalog is a static list in code — `kaos-llm-client` has no `list_models()` (verified). The authoritative model-id registry on PyPI is `kaos_llm_client.cost.MODEL_PRICING` (18 entries as of `kaos-llm-client==0.1.0a3`, `PRICING_LAST_UPDATED == '2026-05'`); the example's catalog is curated from it and lives in `backend/app/services/catalog.py`. **Never paste model ids from memory** — they rot. Verify against `MODEL_PRICING` immediately before any code edit that adds an id.
- **Persistence boundary.** `kaos-agents` persists `SessionMemory` to VFS at `.kaos-vfs/kaos-agents/sessions/{session_id}/memory.json` (verified — note the `sessions/` segment) alongside a `graph.ttl` per session for the GRAPH memory section. Our app-level session metadata (title, model, custom prompt, created_at) lives under a separate VFS namespace — see `ARCHITECTURE.md` § Persistence.
- **Same dependency hygiene as `web:spa`.** `minimumReleaseAge: 4320`, exact pins, `blockExoticSubdeps: true`, `strictDepBuilds: true`, `dangerouslyAllowAllBuilds: false`. Lifted verbatim from `templates/web/spa/pnpm-workspace.yaml`.

## 7. UX requirements

What the user sees on screen, in order of priority:

### 7.1 Login

- Single-page form: text input for bearer token, "Sign in" button.
- On success: redirect to `/sessions` (the session list).
- On failure: red inline error chip. No PII leakage in the error text.
- Logout button in the header on every authenticated page.

### 7.2 Session list (`/sessions`)

- Left sidebar (~280 px), full-height.
- Header row: app name (left), "New chat" primary button (right).
- Sessions sorted descending by `last_message_at`.
- Each row: title (auto-derived from first user message, truncated), relative timestamp, hover-revealed menu (rename, export, delete).
- Empty state: hero illustration + the same 4 starter cards as the `web:spa` template's `EmptyState.tsx`.
- Click row → navigate to `/sessions/:id`.

### 7.3 Chat (`/sessions/:id`)

- Main column max-width 768 px, centered, scrollable.
- Each message: `Message` component from `packages/ui` (user / assistant / tool / error variants).
- Below the last user message and during streaming: `TurnStatus` pill (Thinking… → Running tool → Step 2 → Done).
- After turn completion: `UsageChip` shows tokens + USD cost.
- Composer fixed to the bottom of the main column (mirrors the template's `Composer.tsx`).
- Right rail (~320 px, collapsible): the "session settings drawer" — model picker, custom system prompt editor, toolset toggle, transcript export buttons.
- Loading a session on cold visit: skeletons + a single `GET /v1/sessions/:id` round-trip.

### 7.4 Settings drawer

Layout per `UX-LANGUAGE.md` § 4.7 (right-side sheet, no tabs, single scrollable column, trigger = avatar at bottom-left of sidebar).

- **Model picker** — popover from a chip in the composer chip row (per UX-LANGUAGE § 4.3) AND a default selector in the drawer. Populated from a static catalog matching `kaos_llm_client.cost.MODEL_PRICING`. Initial catalog (verified 2026-05):
  - `anthropic:claude-haiku-4-5` (default, recommended for everyday chat)
  - `anthropic:claude-sonnet-4-6`
  - `anthropic:claude-opus-4-7` (latest Opus — NOT `4-6`)
  - `openai:gpt-5`
  - `openai:gpt-5.5`
  - `openai:gpt-4.1-mini`
  - `google:gemini-2.5-flash` (dot, not dash)
  - `google:gemini-2.5-pro`
  - `xai:grok-3`
  - `xai:grok-3-mini`
- **System prompt** — multi-line textarea; pre-filled with the default; per-session.
- **Tool policy** (TR-1..TR-13) — per-category checkboxes + preset picker + auto-narrow toggle, replacing the legacy single "Enable read-only tools" checkbox. Categories are populated from `GET /v1/chat/categories` (sourced from `kaos_agents.registry.default_tool_group_registry` which `kaos_ui.agents.register_kaos_tool_groups` populates at startup).
  - **Categories shipped**: `documents` (kaos-pdf, kaos-office-parse, kaos-content), `citations` (kaos-citations), `vfs` (kaos-core-vfs, kaos-core-artifacts), `web` (kaos-source-*).
  - **Default ceiling**: `{documents, citations, vfs}`. `web` is opt-in because of cost and privacy implications — Federal Register / EDGAR / eCFR / GovInfo / GLEIF connectors hit the live internet from the user's host.
  - **Auto-narrow planner** (TR-5/TR-6): when on (default), the `TurnToolPolicy` Program runs before each tool-able turn — a single Haiku-class LLM call that picks the smallest set of categories within the ceiling that this turn needs. Web for research questions; documents for upload questions; etc. Confidence < 0.6 → fall back to the full ceiling. Cost target: ≤ $0.0002/turn. Latency target: ≤ 300ms p95.
  - **Wire shape**: `SessionMeta.tool_set: {allowed_groups: string[], denied_tools: string[], auto_narrow: boolean}`. Backward-compat: legacy meta sidecars with only `tools_enabled: bool` migrate at load — `False` → blocked ceiling, `True` → default ceiling. The `tools_enabled` property is a derived `@computed_field` for one release window.
  - **Hard floor**: `denied_tools` is the per-session deny list that always wins over `allowed_groups`. Write tools (`kaos-office-write-*`) are never bridged, so a future write surface cannot slip into a session just because the user enabled the office group.
  - **Transparency**: a per-turn `tool_policy_decided` SSE event drives a `<ToolPolicyBadge>` chip above the assistant message — "Tools: web · 95%" — clickable for the planner's reasoning. `<CostStrip>` shows planner cost as a separate "Planner" row.
- **Save** button — issues a PATCH to our metadata router (see `ARCHITECTURE.md` § 3.4) and closes the drawer. Settings apply to the **next** turn (Agent is built fresh per turn).
- **Export** — two buttons: "Download Markdown" and "Download JSON." Pure client-side render from the session detail payload.

### 7.5 Empty / error states

- Empty session list — hero, starter cards, plain "New chat" CTA.
- API down — banner: "Backend unreachable. Check the server logs." Retry button.
- LLM error mid-turn — inline `Message` of variant `error`, with `what / how_to_fix / alternative` content from the `RunError` event payload.
- Aborted turn — UI shows a small "Stopped" chip on the trailing assistant message.

## 8. Functional requirements

A flat list of capabilities, each testable on its own.

### Backend

The example's backend is **`kaos_agents.api.server.create_app()`** + a thin extension layer (verified PyPI finding — see `ARCHITECTURE.md` § 4). Most of the route surface ships with kaos-agents; we add two extension routes and a metadata sidecar.

Kaos-agents-owned (auto, do not reimplement):
- F-A1. `POST /v1/sessions` — create session.
- F-A2. `GET /v1/sessions/{id}` — session state.
- F-A3. `DELETE /v1/sessions/{id}` — delete session.
- F-A4. `POST /v1/sessions/{id}/messages` — SSE stream.
- F-A5. `GET /v1/sessions/{id}/memory/{section}` — read a memory section.
- F-A6. `POST /v1/sessions/{id}/memory/search` — BM25 search a section.
- F-A7. `POST /v1/runs/{run_id}/approve` — resume an interrupted run (tool-call approval — out of v1 UI scope, but the endpoint ships).
- F-A8. `GET /openapi.json`, `/docs`, `/redoc` — auto.
- F-A9. Bearer auth via `KAOS_AGENTS_API_API_TOKEN` (double-`API_` is the actual env var name; see `PATTERNS.md` P-001 for the pydantic-settings prefix quirk). Kaos-agents refuses to start without it unless `KAOS_AGENTS_API_API_ALLOW_UNAUTH_LOCALHOST=1` is set AND the request originates from `127.0.0.1` / `::1`.
- F-A10. CORS via `KAOS_AGENTS_API_API_CORS_ALLOW_ORIGINS`.

Example-owned (we implement):
- F-B1. `GET /v1/models` — static catalog: `[{id, label, provider, context_window?, recommended_for?}]`.
- F-B2. `GET /v1/chat/sessions` — list our session metadata (title + model + last_message_at + message_count), newest first. Pagination via `?limit=&cursor=`. Joins our metadata sidecar to kaos-agents session presence.
- F-B3. `GET /v1/chat/sessions/{id}/meta` — our metadata sidecar payload.
- F-B4. `PATCH /v1/chat/sessions/{id}/meta` — update `title` / `model` / `system_prompt` / `tools_enabled`.
- F-B5. `POST /v1/chat/sessions/{id}/messages` — **proxy** to kaos-agents `POST /v1/sessions/{id}/messages` after looking up the stored `model` + `system_prompt` + `tools_enabled` from our metadata and threading them into the request body. This is the only route that actively wraps a kaos-agents route; everything else is parallel.
- F-B6. `GET /v1/chat/sessions/{id}/transcript?format=markdown|json` — server-side transcript export (also implemented client-side for instant download; this endpoint exists for "share a link" use cases).
- F-B7. Settings validation: production env refuses `KAOS_AGENTS_API_TOKEN` < 32 chars.

The SPA calls `/v1/chat/*` for everything UI-facing; `/v1/sessions/*` is the kaos-agents-native surface the SPA's generated client *can* hit directly but doesn't need to for normal flows.

### Frontend
- F-F1. Login route + auth context that calls `refresh()` on app boot.
- F-F2. `/sessions` route — renders session list from TanStack Query; mutation for new-chat.
- F-F3. `/sessions/:id` route — paginated history (`useQuery`) + live streamer.
- F-F4. Exhaustive `switch` on the 15 event types, each mapped to a render strategy.
- F-F5. Composer reads keyboard (Enter = send, Shift+Enter = newline) and supports `AbortSignal` via the abort button.
- F-F6. Settings drawer — controlled component, optimistic update, server confirm.
- F-F7. Transcript export — pure-client Markdown serializer + JSON download.
- F-F8. Session sidebar — keyboard navigation (`j` / `k` to move between sessions), Cmd-K for new chat.

### Persistence
- F-P1. Session metadata file: `.kaos-vfs/single-user-chat/sessions/{id}/meta.json`.
- F-P2. Agent memory: `.kaos-vfs/kaos-agents/{id}/memory.json` (managed by `kaos-agents`, not us).
- F-P3. Concurrent-write safety: writes go through `kaos_core.artifacts.VirtualFileSystem` which fsyncs.

## 9. Non-functional requirements

- **NF-1. Performance.** First delta < 2 s on Claude Haiku 4.5 from a warm process. History load < 200 ms for a session with 50 messages.
- **NF-2. Bundle.** SPA gzipped JS < 250 KB (the template baseline is ~131 KB gzipped — we add a sidebar + drawer, budget 100 KB more).
- **NF-3. Accessibility.** Composer textarea, model picker, and session-list rows are keyboard-navigable. Focus rings visible. ARIA roles on the chat log.
- **NF-4. Security.** v1 stores the bearer in `localStorage` (XSS surface — dev-only; see § 6 Auth). Phase 4+ moves to HttpOnly+Secure+SameSite=Strict cookies via an example-level wrapper around `create_app()`. Other invariants regardless of phase: CSP headers via Caddy, no `dangerouslySetInnerHTML` on streamed content, markdown rendered through `markdown-it` with `validateLink` whitelist (http/https/mailto only), external links pinned to `target=_blank rel="noopener noreferrer"`, login `?redirect=` sanitized to same-app paths via `safeRedirect` in `apps/spa/src/routes/login.tsx`, uploads bounded by `max_upload_bytes` enforced via chunked streaming reads (no full-body buffer before validation).
- **NF-5. Observability.** `kaos_core.logging.get_logger()` everywhere. Each turn carries `session_id` + `trace_id` in log records. `LoggingHook` from `kaos_agents.hooks.builtin` registered with the Runner.
- **NF-6. Cost guard.** Default budget cap of $0.50 per turn via `kaos-agents` `BudgetExceeded` event handling.

## 10. Out-of-scope dependencies

- No SQLite. No Postgres. No Redis.
- No background workers. SSE happens in the request handler thread.
- No third-party auth (Auth0, Clerk, etc.).
- No analytics (Plausible, PostHog, etc.).
- No SSR. SPA only.

## 11. Open questions

Marked as open for the reviewer; defaults proposed in `ARCHITECTURE.md`.

- **OQ-1.** Where exactly does session metadata live — sibling-of-agent-memory VFS file (proposed), or merged into the agent's `AUDIT` memory section? **Resolved as sibling-of-agent-memory VFS file** (see ARCH § 6); revisit if `create_app()`'s POST /v1/sessions accepts a config blob we can store there instead.
- **OQ-2.** Do we install `LoggingHook` only? *Resolution:* `CostTrackingHook` is **not required** for the `UsageChip` — `UsageObserved` events already carry `total_tokens` and `cost_usd` per-turn (verified). Install `LoggingHook` only; revisit if we want session-total rollups.
- **OQ-3.** Should the tool toggle be per-session (proposed) or global (per-installation)? *Proposed:* per-session via `Agent.tools` glob.
- **OQ-4.** Does the example ship a Postgres docker-compose for parity with `web:spa`'s optional Postgres path? Proposed: yes, but unused — copy verbatim for consistency.
- **OQ-5.** Does kaos-agents' `POST /v1/sessions` accept extra metadata fields (title, model override, system prompt) in the body, or does it ignore them? **Phase 1 must verify** with a live request; if accepted, we can collapse our metadata sidecar into kaos-agents' session state instead of maintaining a parallel store.
- **OQ-6.** Should the proxy route `POST /v1/chat/sessions/{id}/messages` re-stream the SSE locally, or HTTP-redirect to `/v1/sessions/{id}/messages`? *Proposed:* re-stream — keeps the wire-auth surface uniform (one bearer for the whole API) and lets the SPA's typed client treat it as a normal route.

## 12. Dependencies on other KAOS modules

Pins verified against PyPI on 2026-05-14. **`kaos-llm-core` must be declared explicitly** — `kaos-agents==0.1.0a1` does not pull it transitively, and `from kaos_agents import Agent` will raise `ModuleNotFoundError` without it.

| Package | Pin | Role |
|---|---|---|
| `kaos-core` | `>=0.1.0a6,<0.2` | Runtime, `KaosContext`, VFS, logging, settings base. |
| `kaos-agents` | `>=0.1.0a1,<0.2` | Agent, Runner, SessionMemory, events, hooks, **`api.server.create_app()`**. |
| `kaos-llm-core` | `>=0.1.0a7,<0.2` | **Required by kaos-agents** for `AgentPattern.CHAT` dispatch — NOT transitive in 0.1.0a1. |
| `kaos-llm-client` | `>=0.1.0a3,<0.2` | Model transport + `cost.MODEL_PRICING` (our model catalog source). |
| `kaos-content[markdown]` | `>=0.1.0a6,<0.2` | Optional. Pulled in if `tools_enabled=True`. |
| `kaos-pdf` | `>=0.1.0a2,<0.2` | Optional. |
| `kaos-office` | `>=0.1.0a2,<0.2` | Optional. |

Frontend has no kaos dependencies beyond a synced copy of `packages/ui` (see `ARCHITECTURE.md` § 8 and `PLAN.md` Phase 0 for the `scripts/sync-ui.sh` strategy).

## 13. Versioning

- Tracks `kaos-ui` versioning. Example versions don't appear in any PyPI release in v1.
- Each `docs/` doc has a "Last updated" line at the top; bumped on substantive edits.
