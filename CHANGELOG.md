# Changelog

All notable changes to `kaos-ui` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Per-turn StateSnapshot writer (Issue 5)

Closes the plan §Issue 5 acceptance row "State snapshot per turn:
`runs/turn-NNNN/snapshot.json` written; replay tool can resume
from it."

* **New service module** `app/services/state_snapshot.py` —
  `write_turn_snapshot(*, runtime, session_id, turn_index, run_id,
  model, tenant_id, build_sha, sidecar_records, turn_cost_usd,
  turn_tokens)` writes a compact `snapshot.json` to
  `runs/turn-NNNN/snapshot.json`. Schema v1 carries
  snapshot_version, session_id, turn_index, run_id, model,
  tenant_id, captured_at, build_sha, tool_calls[] (tool_name,
  is_error, duration_ms, cost_usd, started_at), and totals
  (cost_usd, tokens, tool_call_count, tool_error_count).
* **Wired into Step 4 of `persist_turn_completion`** —
  the chat router threads run_id, meta.model, and settings.build_sha
  through to the BackgroundTask, which calls `write_turn_snapshot`
  AFTER the LLM auto-titler so the snapshot reflects the final
  committed turn state. Failure is best-effort (logged, not
  raised) — the sidecar is the source of truth; snapshot is the
  summary.
* **9 unit tests** in `tests/unit/test_state_snapshot.py` covering
  the canonical path, required field set, ToolCallRecord
  serialisation, optional-field handling, JSON round-trip, error-
  count semantics, missing-runtime short-circuit, happy-path
  VFS write, and swallowed-VFS-failure invariant.

Replaceable with the canonical kaos-agents
`StateSnapshot.from_invocation` + `to_json` when the SPA grows a
wired TurnInvocation accumulator (Phase 6+ per kaos-agents
governance roadmap); the file path and consumer-visible schema
stay the same across the swap.

### Added — BAA / HIPAA enforcement gate in single-user-chat backend (Issue 4)

Closes the SPA half of launch-blocker plan §Issue 4
(`kaos-modules/docs/plans/2026-05-22-launch-blocker-top-10.md`).
When a session is flagged `hipaa_required=True` and the resolved
provider is not BAA-eligible, the chat router refuses the message
turn at the edge with HTTP 403. When a non-empty
`allowed_providers` list is configured, off-list providers are
likewise refused — independent of `hipaa_required`.

* **New service module** `app/services/baa_gate.py` —
  `assert_session_baa_compliance(*, model, hipaa_required,
  allowed_providers)` + typed `TenantPolicyError` /
  `TenantPolicyViolation`. Conservative default: only Anthropic /
  OpenAI / Google / Azure-OpenAI / AWS-Bedrock are flagged
  BAA-eligible (operators verify their actual signed contract).
* **Chat router wiring** — `POST /v1/chat/sessions/{id}/messages`
  calls `assert_session_baa_compliance` AFTER the per-turn model
  override but BEFORE the upstream POST, so the gate sees the model
  about to be billed. On trip, raises `HTTPException(403,
  detail={"kind": "tenant_policy_violation", "constraint": ...,
  "provider": ..., "model": ..., "message": ...})` — typed body
  for the UI to render a specific "BAA required" or
  "off-allowlist" banner.
* **13 unit tests** in `tests/unit/test_baa_gate.py` covering
  provider inference from `provider:model` and bare-model shapes,
  unknown-provider fail-closed, the `hipaa_required=False` bypass,
  the five BAA-eligible providers, the explicit xAI refusal,
  allowlist empty-vs-set semantics, allowlist precedence over the
  BAA gate, and the violation payload contract.

Vendored locally until kaos-llm-client 0.1.3+ ships
`profiles.assert_baa_compliance` on PyPI; the helper has the same
signature and will be swap-replaceable in one commit.

## [0.1.0a13] — 2026-05-20

### Added — SettingsSheet AgenticLoop budget caps (#312)

The settings sheet now exposes the three independent AgenticLoop hard
caps as a "Loop budgets" fieldset below the auto_loop toggle:
`max_loop_iterations` (1-10, default 3), `max_loop_cost_usd` (>0, ≤10,
default $0.25), `max_loop_wall_clock_seconds` (>0, ≤600, default 60).
Disabled when auto_loop is OFF since the caps only apply to the
multi-iteration path. Backend `ToolSetUpdateBody` extended with
matching optional fields + `ge`/`gt`/`le` validation that mirror the
canonical `SessionPolicyWire` constraints. PATCH
`/sessions/{id}/tool-set` propagates the three new fields through the
same `policy_updates` dict path the other policy toggles use. The
SPA's submit handler clamps + coerces to documented bounds before
PATCH so empty/non-numeric inputs never send NaN.

## [0.1.0a12] — 2026-05-20

The Stable+1 sweep release. Closes 8 backlog items spanning architectural
debt (#447), UX polish (#341, #309, #310, #313, #314, #315, #316, #317),
and follow-on documentation. Ships shared primitives in the
`@273v/kaos-ui-react` package so future surfaces have a consistent
visual language for empty / loading / error states.

### Added — Shared UI primitives in `@273v/kaos-ui-react/chat`

- **`<EmptyState>`** — single visual treatment for "nothing here yet"
  panels: optional icon + headline + description + CTA, with default
  + compact size variants. Replaces the three+ ad-hoc empty-state
  implementations across the panels. (#315)
- **`<SkeletonLine>` / `<SkeletonRow>`** — Tailwind-pulse loading
  primitives with `motion-reduce` discipline + sr-only AT
  announcement. (#316)
- **`<ErrorBanner>`** — destructive/warning two-tone banner with
  optional retry + dismiss, `role="alert" aria-live="polite"`. (#317)

### Added — Audit-trace endpoint

- `GET /v1/chat/sessions/{id}/audit-trace` proxies kaos-agents'
  canonical `/v1/sessions/{id}/memory/actions` so external consumers
  (kaos-audit-session CLI, debug overlays, downstream analytics) have
  one SPA-side URL pointing at the authoritative full action trace.
  Closes the architectural confusion that the SPA sidecar JSONL was
  the right audit source — it isn't, by design. The sidecar is the
  wire-level chip-UI subset; this endpoint is the canonical trace. (#447)

### Added — Document remove affordance

- `DocumentExplorer` now accepts `onRemove(filename)` + `removing`
  props. Renders a trash icon on each file card with a two-click
  confirm pattern (first click → Check icon + destructive styling;
  second click → commit; auto-resets after 4s of inactivity). Wired
  through to `useDeleteFile(sessionId)` in the SPA host. The backend
  DELETE endpoint already existed. (#309 / #341)

### Added — Citations panel grouping toggle

- Per-message vs per-kind grouping toggle in the panel header (2-button
  segmented control). New `KindBadge` component with coarse category
  coloring (legal=blue, finance=green, accounting=amber, identifier=zinc)
  so users can scan a mixed-kind list and see the dominant domain. (#310)

### Added — Session kebab export submenu

- The session list-item kebab now exposes three Export entries
  (Markdown / JSON / DOCX) wired to the existing `/transcript?format=...`
  backend endpoint via an `ExportMenuItem` helper that does
  authenticated fetch + blob + browser save. (#313)

### Changed — AgenticLoop UX composition + spacing pass

- `Message.tsx` article wrapper now uses `space-y-3` so the AgenticLoop
  per-message primitives (ToolPolicyBadge, ElevationPill, ReasoningSummary,
  PlanCard, ToolCallTimeline, body, CapabilityApproval, GoalCheckBadge,
  LoopTerminatedBanner, UsageChip) get consistent vertical rhythm
  instead of each component managing its own ad-hoc `mb-3`. Removed
  the redundant wrapper around PlanCard. (#314)

### Changed — Recorder scope documentation

- `TurnToolCallRecorder` docstring now explicitly documents the
  wire-level-only scope: chips show user-visible tool activity
  (`Span(TOOL_CALL, ...)` events); planner / critic / Signature /
  auto-titler internal LLM calls land in `SessionMemory.ACTIONS` only.
  Two surfaces, two consumers, both correct. Pairs with the new
  audit-trace endpoint above. (#447)

## [0.1.0a11] — 2026-05-20

The 0.1.0b1-followup patch. Fixes the two P0s surfaced during the
0.1.0b1 Chrome MCP Stage 7 acceptance against freshly-published PyPI
artifacts, plus #401 (legacy-session tool-chip bleed) and #342
(tool-call persistence enrichment with cost/timing/plan-linkage).
All four are SPA-backend changes in the chat router and recorder;
the kaos-ui Python distribution is the host package.

### Fixed — Memory ≠ UI (#519)

`SessionMemory.MESSAGES` persisted the AgenticLoop's max_iterations
refusal text while the UI displayed the worker's successful answer —
violating the invariant that memory must match what the user saw.
Root cause: the SPA backend's `last_iter_text` accumulator in
`app/routers/chat.py` blindly took the last `turn_summary` event's
text. When a refusal terminator fires *after* a successful worker
iteration (typical max_iterations / cost_exceeded / wall_clock_exceeded
path), the post-summary text_delta is the start of a new phase, not
an append to the prior. The fix mirrors the SPA event-handler.ts #508
replace-on-stream-closed logic in the backend: track `streaming_closed`
across the event loop; when the next text_delta arrives after a
`turn_summary`, RESET the iter accumulator + last_iter_text before
appending. Result: persisted text exactly matches the UI's final
rendered content.

### Fixed — Legacy-session tool-chip bleed (#401)

History hydration's sidecar lookup used `enumerate(assistant_msgs)`
as the turn-index key, which assumes one assistant message per logical
turn. Legacy sessions created against kaos-agents pre-a18 (before the
#458 / #504 canonical-turn persist) have N assistant messages per
turn — one per AgenticLoop iteration — and the assumption broke:
`turn-0000.jsonl` attached to iteration-1's message, `turn-0001.jsonl`
didn't exist for iteration-2 so it fell back to memory/actions with
the wrong time window, and chips bled across turns. The new logic
computes `turn_index` from the count of preceding user messages and
identifies the LAST assistant in each consecutive-assistant group as
the sidecar owner. Leaf iterations (critic-rejected intermediates)
get no chips — correct, because they're not the user-facing answer.
New sessions are unaffected (one assistant per turn → owner mark
always True for the single assistant).

### Enhanced — Tool-call sidecar persistence enrichment (#342)

`ToolCallRecord` now carries `duration_ms` (wall-clock from
`Span(TOOL_CALL, COMPLETE).duration_ms`), `cost_usd` (from
`ToolCallSummary.cost_usd` — non-zero when the tool itself drove
an LLM call, e.g. RAG verifier or delegated sub-agent), `plan_id`,
and `step_id`. All four are optional; older kaos-agents versions
that don't emit them leave the fields `None`, so legacy sidecars
still parse cleanly. Unblocks downstream UX work that wants to show
per-call timing chips and surface cost contribution per tool.

### Fixed — Cost telemetry zero in SessionMeta (#520)

`/v1/chat/sessions/{id}/meta` returned `last_turn_cost_usd=0.0` and
`last_turn_tokens=0` even when the UsageChip showed real numbers
($0.0103 / 24.4k tokens observed during Stage 7). Root cause was
structural: `TurnUsageRecorder` exists in
`app/services/tool_call_recorder.py` but was never instantiated in
`app/routers/chat.py`. Every call to `persist_turn_completion`
defaulted `turn_cost_usd=0.0` / `turn_tokens=0`. Fix: instantiate
`TurnUsageRecorder` alongside `TurnToolCallRecorder`, observe SSE
events on both, snapshot to `persist_snapshot` in the finally-block,
pass through to the BackgroundTask. The recorder prefers the
`turn_summary` aggregate (covers Signature-level calls the SPA
otherwise misses, per #342) and falls back to summing
`usage_observed` events when the stream terminated early. Affects
both `last_turn_*` and the `total_*` cumulative accumulators in
`persist_turn.py`.

## [0.1.0a10] — 2026-05-20

The "chat-stack honesty" release. Lands the P0 final-synthesis fix,
the per-turn cost telemetry, the build-SHA stale-session badge, the
removal of the Runner monkey-patch, and the kaos-ui-react chronological
chat-transcript redesign. Bumps the kaos-llm-core pin to 0.1.0a17 in
the SPA backend's `uv.lock`. Cuts npm `@273v/kaos-ui-react@0.1.0-alpha.9`
alongside (see `packages/kaos-ui-react/CHANGELOG.md`).

The release is the Stage 0b output of the stable-release plan
(`kaos-modules/docs/plans/2026-05-20-stable-release-plan.md`).
Following the A3 path: ship the in-flight snapshot as a single
thematic release rather than splitting into per-group PRs.

### Fixed — Final-synthesis truncation on attorney-grade deliverables (P0-1)

Closes `kaos-modules/docs/plans/2026-05-18-cross-layer-issue-inventory.md` § P0-1.

Persona #4 (10-persona NDA matrix) — and three other personas — were
losing their final answer to a 67- to 200-character polite preamble
("I've gathered all the information needed and am ready to provide
my final answer.") even though every search, document parse, and
citation step had completed correctly. Root cause was at the prompt
layer, not at any limit (`max_react_iterations`, `turn_budget_usd`,
`max_tokens`): modern frontier models satisfy the agentic loop's
goal-check on the work they've *announced*, then emit a meta-response
about being ready instead of the deliverable itself.

`examples/single-user-chat/backend/app/settings.py` —
`_DEFAULT_SYSTEM_PROMPT` now ends with a "Deliverable contract"
section that names the expected output shapes (table / list /
summary / comparison / CSV / memo / citations) and requires them to
be emitted inline in the same response that satisfies the goal.
Verified on Persona #4 (5-jurisdiction enforceability comparison)
against Opus 4.7: 5/5 jurisdictions, full CSV table, 2,678
characters, no fabrication.

### Added — Per-turn cost telemetry persisted to `SessionMeta` (P1-3)

Closes inventory § P1-3.

The SPA's `SessionMeta` carried only header-level cost/token
counters in the SSE stream; nothing was ever persisted, which left
the sidebar (and any future cost audit) with `null` cost and tokens
on completed sessions. The new pipeline:

- `backend/app/services/tool_call_recorder.py` — new
  `TurnUsageRecorder` taps both `usage_observed` and `turn_summary`
  events. The aggregate `turn_summary` wins when present; otherwise
  the recorder sums `usage_observed` deltas (handles models /
  providers that don't emit a summary).
- `backend/app/routers/chat.py` — wires `TurnUsageRecorder` next to
  `TurnToolCallRecorder`, snapshots `(cost_usd, tokens)` into
  `persist_snapshot`, and threads them into
  `persist_turn_completion`.
- `backend/app/services/persist_turn.py` — reads prior `SessionMeta`,
  computes the running totals, and patches `last_turn_cost_usd` /
  `last_turn_tokens` / `total_cost_usd` / `total_tokens` in one
  `store.patch(...)` call. Race-free under the existing patch
  semantics (caller provides absolute values, store doesn't compute).
- `backend/app/models.py` + `backend/app/persistence/sessions.py` —
  fields added to both `SessionMeta` and the lightweight
  `SessionSummary` row type so the sidebar can render them without
  fetching the full meta document.
- `apps/spa/src/lib/api-types.ts` — `SessionSummary` mirrors gain
  optional `last_turn_cost_usd` / `total_cost_usd` / `total_tokens`.

### Added — Build SHA + stale-session badge (P3-10)

Closes inventory § P3-10.

When kaos-* packages are upgraded under a running SPA, in-flight
sessions can exhibit behavior that predates fixes in the deployed
build (the bug-hunting equivalent of "did this user hit the version
where X was broken?"). The SPA now stamps every session with the
build identity:

- `backend/app/routers/health.py` —
  `@functools.lru_cache current_build_sha()` returns a 12-char
  sha256 hash over the sorted `(pkg, version)` tuples of all
  installed `kaos-*` packages. `/v1/health` now returns
  `{"status": "ok", "build_sha": "<12-char>"}`.
- `backend/app/persistence/sessions.py` — `SessionStore.create()`
  stamps `meta.build_sha = current_build_sha()` at session-create
  time. Pre-fix sessions persist with `build_sha = None` and are
  treated as "pre-tracking, build identity unknown" rather than
  "stale".
- `apps/spa/src/hooks/use-health.ts` (new) — TanStack Query hook
  with a 5-minute stale time (build SHA is process-lifetime
  immutable).
- `apps/spa/src/components/sessions/SessionListItem.tsx` — sidebar
  rows show a small "older" pill (with `role="status"` for screen
  readers and a `title` tooltip) when both SHAs are known and
  differ.

### Removed — `Runner._build_internal_agent` monkey-patch (P0)

`backend/app/main.py` deleted the ~50-line module-import-time monkey
patch that mutated `kaos_agents.Runner._build_internal_agent` to
rewrite tool-call file paths. The patch was redundant: the manifest
the SPA assembles before the turn already gives the agent absolute
VFS paths through the URI contract (kaos-core 0.1.0a10+ +
`default_vfs_namespace`). Removing the patch eliminates an entire
class of shadow-of-upstream-types bugs and the start-up race where
the patch was installed against the wrong `Runner` symbol when
multiple kaos-agents wheels were on the path.

### Changed — `ANTHROPIC_TOOL_FALLBACK.default_max_tokens` 8K → 64K

`kaos-llm-client/kaos_llm_client/profiles.py` raised the fallback
provider profile's `default_max_tokens` from 8192 → 64000 and the
Claude 3.x legacy fallback from 4K → 64K. The Anthropic API clamps
to the physical model cap upstream, so values larger than the cap
are safe; values smaller actively truncate frontier-model
deliverables (the original P0-1 symptom looked like a token cap
before we traced it to the prompt). 64K is the floor for an
attorney-facing surface.

### Changed — Frontier-tier defaults across SPA + scaffolding templates

The shipped single-user-chat SPA and the three SPA-/dashboard-/TUI-
template scaffolds (`kaos-ui new web:spa`, `... dashboard:streamlit`,
`... tui:textual`) all defaulted to `anthropic:claude-haiku-4-5` —
the cheap routing tier. These defaults flow straight to end users
who scaffold a new project. For audiences that ship a deployed app
to attorneys / clinicians / financial pros, that default is
load-bearing the wrong way: the inference-cost delta between haiku
and a frontier reasoning model is rounding error against the cost
of a wrong answer.

- **`examples/single-user-chat`** — `AppSettings.default_model`
  flipped `claude-haiku-4-5` → `claude-opus-4-7`. `auto_title_model`,
  `summarizer_model`, `agentic_planner_model`, `agentic_goal_check_model`
  all promoted Haiku → Sonnet 4.6 (the planner / goal-check models
  ARE the routing decisions that gate "search the corpus" vs
  "answer from prior" — Haiku-grade routing was directly upstream of
  the section-number fabrication seen in the persona matrix).
  `_BASELINE_TITLE_MODEL` baseline matched to Sonnet so the
  decoration-time pin no longer triggers a per-call rebuild.
  Catalog narrowed to `gpt ≥ 5.4` / `claude ≥ 4.5` / `gemini ≥ 2.5`
  (no xAI/Grok, no `gpt-4.1-mini`, no `gpt-5`) — 8 entries, frontier
  first. `.env.example`, `models.py` docstring, error-message hint
  all match the new default.
- **`kaos_ui/templates/web/spa/.env.example`,
  `kaos_ui/templates/web/spa/backend/app/settings.py.tmpl`,
  `kaos_ui/templates/dashboard/streamlit/.env.example`,
  `kaos_ui/templates/dashboard/streamlit/{module}/settings.py.tmpl`,
  `kaos_ui/templates/tui/textual/.env.example`,
  `kaos_ui/templates/tui/textual/{module}/settings.py.tmpl`** —
  default `APP_LLM_MODEL=claude-opus-4-7`, with an inline comment
  warning against downshift for professional audiences.
- **Docs** — `docs/templates/textual.md`,
  `examples/single-user-chat/docs/{PRD,PLAN,ARCHITECTURE}.md`,
  `examples/single-user-chat/README.md`,
  `packages/kaos-ui-react/src/chat/ModelPicker.tsx` (docstring),
  `packages/kaos-ui-react/src/hooks/use-cost-aggregation.ts`
  (docstring) — all default examples + recommendations switched
  to `claude-opus-4-7`. PRD § 5 + § 6 + § 7.4 updated with the
  attorney-audience rationale.

Existing kaos-agents library defaults (`KAOS_AGENT_DEFAULT_LLM_MODEL`
etc.) are NOT touched — those are an upstream library concern; this
release narrows what kaos-ui ships to its own end users.

## [0.1.0a9] — 2026-05-16

Rolls up both M1 and M5 of `kaos-modules/docs/plans/thin-worker-prompt.md`
into a single tagged release. (Version `0.1.0a8` lived briefly on `main`
in the interim — `_version.py` was bumped when M1 merged, but no
`v0.1.0a8` tag was ever cut. The 0.1.0a9 tag is the first artifact in
this series to reach PyPI; the 0.1.0a8 changelog section below
documents M1 work that landed on `main` but never released as a
standalone version.)

### Changed — Drop redundant tool catalog from worker prompt (M5 of `thin-worker-prompt.md`)

`kaos_ui.agents.augment_instructions` no longer inlines a tool-name
catalog into the system prompt. The catalog reaches the LLM via the
provider's native tool-use API: kaos-agents 0.1.0a5+ bridges
KaosTools into kaos-llm-core Tool objects, ReAct passes their
definitions as the `tools=` parameter to `chat_async`
(`kaos_llm_core/programs/react.py:725`), and modern Claude / GPT /
Gemini surfaces those tools to the model independently of the system
prompt.

Net effect: the steady-state worker prompt drops from ~720 tokens
(M1 baseline) to ~105 tokens — date preamble plus session voice
only. The tools-disabled refusal directive is preserved.

### Removed (BREAKING)

- `kaos_ui.agents.augment_instructions(available_tool_names=...)` —
  the parameter is gone. Callers that imported it should drop the
  argument; the helper no longer needs the catalog.
- `app.services.stream_proxy._instructions_with_corpus` no longer
  accepts `available_tool_names`. Public callers continue to thread
  the catalog through `_build_forward_body` / `stream_chat` because
  it is still used for `_tool_patterns` (SessionToolSet filtering at
  the wire layer).

### Verified

- `kaos-llm-core/programs/react.py:723-728` — tools handed to the
  provider via the native `tools=` parameter and `ToolChoice(type=
  "auto")`, not via inline text.
- `kaos_ui/agents.py` worker prompt budget tightened to ≤300 tokens
  in `tests/unit/test_worker_prompt_budget.py`.

## [0.1.0a8] — 2026-05-16 (not released as a tag — folded into 0.1.0a9)

### Changed — Thin-worker-prompt refactor (M1 of `thin-worker-prompt.md`)

The example backend's worker system prompt is now ~720 tokens (down
from ~1,600), and **no document body is inlined into the prompt at
any point**. Policy decisions (which tools to call, when to search
before clarifying, when to escalate) now flow exclusively through
the kaos-agents Signature decision points (`_TurnToolPolicySignature`
docstring picks `kept_groups`; `_GoalCheckerSignature` returns
verdicts and `next_action`; `AgenticLoop` threads the next-action
as `thinking_note` to the next worker iteration). See the full
plan at `kaos-modules/docs/plans/thin-worker-prompt.md`.

**Removed from the worker prompt:**

- The 400-token "Search-before-answer rule" block in
  `kaos_ui.agents.augment_instructions` (B13 addition) — duplicated
  the planner Signature's group-selection shortcuts in English.
- The 150-token "Search-before-clarify rule" block in
  `app.services.stream_proxy._instructions_with_corpus` (F.11.B) —
  duplicated the critic Signature's "agent said 'I can't' →
  needs_more_work" shortcut.
- The 700-token tool-taxonomy + path-format tutorial in
  `app.settings._DEFAULT_SYSTEM_PROMPT` — the tool catalog is
  injected separately with descriptions; the model doesn't need a
  prose tutorial of every group.
- The F.11.A force-elevation block in `app.routers.chat` that
  widened `SessionPolicy.allowed_groups` to include `documents`+`vfs`
  whenever files were attached. The planner Signature's corpus-kinds
  hint owns that decision — the router carries the policy through
  unchanged.

**`render_session_corpus_markdown` no longer inlines file bodies.**

Pre-refactor, every uploaded file's full markdown serialization
was dumped into the prompt under a `### filename` header, up to a
40,000-char-per-file budget. A 20-file legal upload mix shipped
~200K tokens of inert content into every turn, including replan
iterations the agent didn't read it on. The new output is a
metadata catalog per file: filename, size, content type, the two
VFS paths (bytes + AST), parse status, and the cached one-line
summary. Agents reach the body by calling
`kaos-content-search-document` / `kaos-pdf-extract-page-text` /
`kaos-content-corpus-narrow` with the VFS paths the metadata
block exposed. Mirrors kelvin-agent's `Document.to_compact_dict()`
pattern.

The `per_file_budget_chars` kwarg on `render_session_corpus_markdown`
is retained for back-compat with callers that pass it; it is no
longer consulted.

### Added — Token-budget contract test

`tests/unit/test_worker_prompt_budget.py` (13 tests). Mechanical
guard against the worker prompt regrowing 400 tokens of English
behavior rules — the failure mode that produced the 2026-05-16
dumpster fire. Asserts (a) the rendered prompt is ≤800 tokens
steady state and ≤300 tokens tools-disabled, (b) nine specific
forbidden substrings (hardcoded tool names, imperative behavior
rules) never appear, (c) every tool name appears at most once
(in the catalog). When a future contributor adds a rule to
`augment_instructions`, one of these fires with a pointer to the
right Signature instead.

### Removed

- `test_attached_files_force_documents_and_vfs_into_policy` in
  `tests/integration/test_chat_agentic_loop.py` — the F.11.T
  regression that locked in the F.11.A bypass. Replaced with
  `test_chat_router_passes_policy_through_unchanged` which pins
  the inverse contract: the router must not widen the policy.



### Backend dependency bump — `kaos-agents>=0.1.0a5`

The respond-handler root-cause fix for the `[/response]` scratchpad
leak lives in **kaos-agents 0.1.0a5** (drops the ChatCodec override
in `BaseAgent._simple_respond`, switches to native JSONCodec / JSON
schema). The example backend's `pyproject.toml` floor moves from
`>=0.1.0a4` to `>=0.1.0a5`. Until kaos-agents 0.1.0a5 publishes to
PyPI, `[tool.uv.sources]` resolves it from the
`https://github.com/273v/kaos-agents.git` tag `v0.1.0a5`. The
override block should be removed once the PyPI wheel lands.

### Fixed — B10: scratchpad tags leak in HISTORY hydration

F.11.D's strip only ran on live `text_delta` SSE events. Historical
messages loaded via `GET /v1/chat/sessions/{id}/messages` came back
straight from session memory and rendered the raw `[/response]` /
`<function_calls>{...}</function_calls>` artifacts that older
kaos-agents persisted. Fix:

- Hoisted the strip helper out of `event-handler.ts` into
  `packages/kaos-ui-react/src/lib/text-strip.ts` and re-exported
  from the `kaos-ui-react/lib` barrel as `stripScratchpadTags`.
- The history mapper in `apps/spa/src/routes/_auth.sessions.$id.tsx`
  now wraps assistant `content` through the same strip. User-typed
  messages are NOT stripped (they're never the source of these
  tokens).

Sessions created against kaos-agents 0.1.0a5+ won't accumulate
dirty bytes; this strip protects legacy transcripts.

### Fixed — Bug bundle (B1, B2, B3, B6, B8, B9, B10 / F.11.A-D + T, M.6)

### Added — M.6 SessionPolicy patch surface

The chat router's `PATCH /v1/chat/sessions/{id}/tool-set` now
accepts three additional fields — `auto_elevate`, `auto_loop`,
`persona` — and routes them through `SessionStore.patch_policy`
onto the live `SessionPolicyWire` instead of the legacy
`SessionToolSetWire`. The `SettingsSheet` Tool Policy section
grew three new controls (two checkboxes + a persona picker) so
users can flip these from the right-side sheet.

### Fixed — additional bugs

**B6 — Plan/Act chip stuck on Act, never flips to Plan.** The
chip detected mode from `meta.policy.auto_loop || auto_elevate`
but wrote to `auto_narrow` (because pre-M.6 the SPA's
`ToolSetUpdateBody` only modeled `auto_narrow`). Clicking Plan
flipped a field the chip never read, so the chip silently wedged.
The M.6 wire expansion lets PlanActChip write the correct fields;
the chip now writes `auto_loop` AND `auto_elevate` together to
flag mode transitions.
(`apps/spa/src/components/settings/PlanActChip.tsx`,
`apps/spa/src/lib/api-types.ts`,
`backend/app/models.py`,
`backend/app/routers/chat.py`)

**B8 — Session title stays "Untitled" after first turn.** The
backend auto-titler patches `SessionMeta.title` immediately from
the user's first message, but the SPA's `useSession` query never
got invalidated post-stream — the chat header and sidebar kept
serving cached pre-turn meta forever. Same issue affected
`message_count` (header showed "0 messages" even after a
completed turn). The chat route now invalidates the session
meta, message history, and sessions-list queries on the
pending→idle transition.
(`apps/spa/src/routes/_auth.sessions.$id.tsx`)

**B9 — Raw `<function_calls>` text leaking into UI.** Anthropic
Claude emits its function-calling syntax (`<function_calls>[...]`
`</function_calls>`) as TEXT when tool binding falls off the
native tool_use path — visible as a literal JSON array in the
rendered assistant turn. Extended F.11.D's strip regex to drop
the WHOLE block (opener + JSON body + closer), not just the
trailing tag. The proper provider-side fix lives in
kaos-llm-client / kaos-agents and is tracked separately; this
strip prevents the visual cruft regardless.
(`packages/kaos-ui-react/src/lib/event-handler.ts`)

### Fixed — Bug bundle (B1, B2, B3 / F.11.A-D + T)

**B1 — Composer "typing broken after first chat" hardening.** Could
not reliably reproduce via Chrome DevTools MCP with real keyboard
events; the most plausible root cause for the user's report was a
window of `dist/chat/index.js` pre-transform errors during package
rebuilds. Two real UX bugs in the same family did surface during the
investigation and are fixed:

- `SlashMenu` global keydown listener no longer intercepts Enter /
  Tab / Esc unless the composer textarea is the active element. Means
  pasting a literal `/path/to/file` and pressing Enter now sends the
  message instead of triggering a skill insertion.
  (`packages/kaos-ui-react/src/chat/SlashMenu.tsx`)
- Esc inside the slash menu no longer wipes the entire composer
  draft. Strips only the leading `/<query>` token and preserves
  whatever the user wrote after.
  (`apps/spa/src/routes/_auth.sessions.$id.tsx`)

**B2 — `[/response]` scratchpad-tag leak.** Haiku 4.5 (and other
instruction-tuned models) was emitting `[/response]` closers into
the SPA when the agent's respond handler used `ChatCodec` for the
single-output `RespondSignature`. Root-cause fix lives in
kaos-agents (BaseAgent.\_simple\_respond now uses the default
`JSONCodec` — native structured output via the provider's JSON-schema
path — and strips any residual scratchpad-tag closers post-decode);
UI-side belt-and-suspenders strips `[/\\w+]` / `</\\w+>` from
`text_delta` content in the reducer so a future codec regression
can't reach `Message` rendering.
(`packages/kaos-ui-react/src/lib/event-handler.ts`)

**B3 — Agent asks for clarification instead of searching the
attached PDF.** Pre-existing failure mode where an ambiguous query
("who's teaching 800?") against a session with an uploaded
`course-descriptions.pdf` produced an "I need more context" reply
instead of a `kaos-content-search-document` call. Fixed at two
layers (F.11.A + F.11.B):

- **F.11.A — Backend planner gate** in
  `apps/single-user-chat/backend/app/routers/chat.py`. When the
  per-turn `corpus_headlines` is non-empty, the chat router now
  widens `SessionPolicy.allowed_groups` and `soft_ceiling` to
  include `documents` and `vfs` before handing the policy to
  `run_agentic_turn`. The planner's `ceiling_groups` input thus
  always exposes the doc-search path when there are docs to search.
- **F.11.B — Strengthened corpus directive** in
  `apps/single-user-chat/backend/app/services/stream_proxy.py`.
  The "Documents attached" block now carries an explicit
  "search-before-clarify" rule directing the model to call
  `kaos-content-search-document` / `kaos-pdf-extract-page-text`
  with the user's literal query terms BEFORE asking a clarifying
  question.
- **F.11.T — Regression test** in
  `tests/integration/test_chat_agentic_loop.py` —
  `test_attached_files_force_documents_and_vfs_into_policy`:
  narrows the session ceiling to a single non-doc group, attaches a
  tiny PDF, sends a turn, and asserts the captured `policy.allowed_groups`
  contains both `documents` and `vfs`.

F.11.C (UI fallback pill) is deferred — A+B+T together should kill
the failure live; C would only ship if a smoke pass shows
regressions.

### Changed — Memory: Structured-output-only policy

Recorded a project-wide preference in agent memory: **always prefer
native JSON-schema / structured output for kaos-llm-core
Signatures**; never `ChatCodec` / `XMLCodec`. Modern Claude 4.x /
GPT-5.x / Gemini 2.5 all support first-class structured output —
text-marker codecs cause exactly the `[/field]` closer leakage this
release fixes.

## [0.1.0a7] — 2026-05-16

### Added — Top-5-easiest features from the framework survey

A research pass surveyed 20 LLM chat UI frameworks + flagship products
(assistant-ui, Vercel AI Elements, Open WebUI, LibreChat, Lobe Chat,
AnythingLLM, Chatbot UI, Continue, Cline, Roo Code, shadcn-chat, Letta,
LangGraph Studio, Claude Projects, ChatGPT Atlas, Perplexity Spaces,
Cursor 2.0, Anthropic Console, Cody, Mintlify, Linear Agent) and
produced a ranked list of 10 features to ship next. Full report at
`.screenshots/RESEARCH-next-features.md`. This release lands the **5
easiest** of those 10 — all S- or low-risk M-effort — in a single
coherent batch.

- **F.4 — Plan / Act mode toggle on the composer**
  (`apps/spa/src/components/settings/PlanActChip.tsx`). New chip in
  the composer bottom-left. **Plan** = read-only research (auto-loop +
  auto-elevate OFF — the agent answers without invoking any tool that
  could mutate state). **Act** = full agentic loop (the v0.1.0a4+
  default). Sourced from `meta.policy`, written via the existing
  `usePatchToolSet` hook — single source of truth. Pattern from
  Continue.dev's Plan/Agent toggle and Cline.

- **F.5 — Composer chip area polish**
  (`packages/kaos-ui-react/src/chat/Composer.tsx`). Bumped the Send /
  Stop button to 40×40 (WCAG 2.5.8 — pre-empted a touch-size
  regression Lighthouse caught when the chip row grew). The
  ModelPickerChip + PlanActChip both dock into `leftChips`; thinking-
  effort selector deferred until kaos-agents exposes it on the wire.

- **F.6 — Inline reasoning summary, collapsed by default**
  (`packages/kaos-ui-react/src/chat/ReasoningSummary.tsx`). Renders
  the most-recent `goal_check.rationale` / `next_action` / `missing`
  as a gray-italic 1-line summary above the assistant text. Click to
  expand into the full rationale + iteration / confidence /
  latency metadata. Data already lives on `ChatMessage.goal_check`
  from the SSE reducer — pure UI. Pattern: Claude 4.6 adaptive
  thinking + Vercel AI Elements `Reasoning`.

- **F.9 — Highlight-text-in-document → "Ask about this" prefill**
  (`packages/kaos-ui-react/src/chat/DocumentExplorer.tsx` + chat
  route). Selecting text inside a document summary surfaces a
  floating "Ask about this" pill anchored to the selection. Click →
  composer pre-fills `About this passage from \`<doc>\`:\n\n> <passage>`
  (truncated at 600 chars) and focuses. Pattern: Mintlify highlight-
  to-Ask, ChatGPT Atlas page-aware sidebar.

- **F.3 — Slash commands as filesystem skills**
  (`packages/kaos-ui-react/src/chat/SlashMenu.tsx` +
  `apps/spa/src/lib/skills.ts`). Composer `/` menu loads from a
  `Skill[]` registry. Each skill = (id, name, description, prefill,
  optional persona, optional model, optional `allowed_groups`).
  Picking a skill replaces the composer text with its prefill and
  patches the tool-policy when `allowed_groups` is set. Built-in
  catalog ships 6 skills (Federal Register search, summarize,
  redline, verify, compare, forensics). Keyboard nav: ↑↓ to select,
  ↵ / Tab to insert, esc to dismiss. Pattern: Claude Code Skills
  (`.claude/skills/<name>/SKILL.md`), Linear Agent skills, LibreChat
  Presets.

### Public API additions to `@273v/kaos-ui-react/chat`

- `<ReasoningSummary goal={...} />`
- `<SlashMenu skills={...} query={...} open={...} onPick={...} onClose={...} />`
- `<DocumentExplorer onAskAboutSelection={...} />` prop
- Types: `Skill`, `SkillPersona`, `SlashMenuProps`, `AskAboutSelection`.

### Fixed

- a11y: Composer Send button bumped from 36×36 → 40×40 after
  Lighthouse flagged the touch-target size regression when the
  composer chip row densified.
- a11y: Slash-menu `/id` accent text bumped to `font-semibold` —
  the regular weight at `text-accent` (4.34:1) failed WCAG AA for
  small text; semibold passes.

### Verification

- Lighthouse on the active chat surface: **100 / 100 / 100 / 100**
  (a11y / best-practices / SEO / agentic). 36 audits passed, 0 failed.
- Browser console: clean.
- TypeScript: clean across kaos-ui-react + SPA.
- 96 SPA vitest passing — no regressions.

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

[Unreleased]: https://github.com/273v/kaos-ui/compare/v0.1.0a7...HEAD
[0.1.0a7]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a7
[0.1.0a6]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a6
[0.1.0a5]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a5
[0.1.0a4]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a4
[0.1.0a3]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a3
[0.1.0a2]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a2
[0.1.0a1]: https://github.com/273v/kaos-ui/releases/tag/v0.1.0a1
