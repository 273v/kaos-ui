# Changelog — @273v/kaos-ui-react

All notable changes to this package are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 0.1.0-alpha.1 (planned)

### Added — Tool policy transparency surface (TR-7..TR-12)

- `ToolPolicyDecidedEvent` joins the `KaosAgentEvent` discriminated
  union. Backend-agnostic: kaos-agents itself does not emit this
  event yet; consumers tolerating its absence (eg plain kaos-agents
  0.1.0a1 backends) continue to work unchanged. See the event type's
  docstring for promotion status.
- `ChatMessage.tool_policy: ToolPolicySnapshot` carries the per-turn
  narrowing decision when the backend's planner Program emits it.
- `<ToolPolicyBadge>` in `./chat` renders an inline transparency
  chip above the assistant message ("Tools: web · 95%") clickable
  to expand reasoning + cost + latency.
- `<CostStrip>` (`./debug`) gains a "Planner" row aggregating
  per-session planner cost when at least one `tool_policy_decided`
  event has fired with non-zero cost.
- `ALL_EVENT_TYPES.length` increases from 15 to 16. Event-handler
  dispatch is exhaustive over the new union.

## [0.1.0-alpha.0] — Unreleased

First public alpha. The API surface is documented in
[`README.md`](./README.md); breaking changes between alpha versions
are expected and will be called out here.

### Added — package skeleton (UI-A → UI-F)

- **UI-A.** pnpm workspace + tsup build (ESM + CJS + .d.ts per entry).
  Subpath exports: `/chat`, `/debug`, `/hooks`, `/lib`,
  `/styles.css`, `/tailwind.preset`. Peer deps locked at
  React ≥19, react-dom ≥19, @tanstack/react-query ≥5,
  tailwindcss ≥4 (optional). Theme tokens in `src/theme/tokens.css`
  with light + dark variants, shadcn-naming-compatible.
- **UI-B.** Pure library layer:
  - `KaosAgentEvent` discriminated union covering the 15 kaos-agents
    wire event types + the `span(subject × phase)` cartesian.
  - `applyEvent(state, event)` reducer with exhaustive switch + a
    `_exhaustive: never` guard so new event types break compilation.
  - `<KaosUIProvider transport={{ baseUrl, getToken, fetch }}>`
    context + `useTransport()` reader.
  - `transportFetch` / `transportJson` helpers: auth-aware fetch
    that skips the default `Content-Type: application/json` when
    the body is `FormData` (multipart uploads).
  - `renderMarkdown` (markdown-it) with `validateLink` whitelist
    (http / https / mailto only; external links pinned to
    `target=_blank rel=noopener`).
- **UI-C.** Hooks:
  - `useSendMessage(opts)` — POSTs to `{baseUrl}/sessions/{id}/messages`
    + parses SSE via `eventsource-parser`; owns the AbortController
    and the TranscriptState reducer.
  - `useSessionFiles` / `useUploadFile` / `useDeleteFile` /
    `useBackfillFiles` — TanStack Query mutations + queries
    against `/sessions/{id}/files` and `/files:backfill`.
  - `useCitations(sessionId, messages)` — post-turn extractor that
    runs `POST /sessions/{id}/citations` over each finalized
    assistant message and accumulates `Map<message_id, Citation[]>`
    across the session.
  - `useCostAggregation(events)` — derives per-model {calls,
    input_tokens, output_tokens, total_tokens, cost_usd} rollups
    over the raw `usage_observed` event list.
- **UI-D.** Chat components, presentational + Tailwind only:
  `<Composer>` (auto-grow textarea + send + stop + paperclip),
  `<Message>` (markdown render + inline tool-call cards + usage chip),
  `<TurnStatus>` (status pill), `<DropZone>` (full-viewport drag
  overlay with depth-counter flicker fix), `<FileChips>` (uploaded
  files row with overflow → onShowAll), `<CitationsPanel>` (right
  rail grouped by kind, hides `id`/`supra`/`infra`),
  `<ModelPicker>`.
- **UI-E.** Debug surface — `<RunInspector>` umbrella combining
  `<CostStrip>` (live $ / tokens / per-model rollups), `<EventsLog>`
  (auto-scroll log + click-to-expand JSON), `<FilterChips>` (7
  event-type categories), and `<JsonTree>` — a React port of the
  Alpine `jsonTree()` from `kaos_agents.examples.viewer`. Same
  visual surface: caret toggle, copy-path / copy-value hover
  actions, long-string preview + toggle, redaction badge, plain-CSS
  `.kaos-jt-*` classes so the tree renders identically with or
  without Tailwind.
- **UI-F (example consumer)** — refit `examples/single-user-chat`
  to import everything from `@273v/kaos-ui-react/*`. 19 inline
  source files deleted; the app is now a real reference consumer.
  Vitest still runs against the package's reducer exports.

### Added — polish (POL-A → POL-G)

- **POL-A.** Per-message stats: `ChatMessage` gains `started_at`,
  `latency_ms`, `input_tokens`, `output_tokens` alongside the
  existing `tokens` / `cost_usd`. `applyEvent` accumulates usage
  across multiple LLM calls within a turn (previously the chip
  showed only the last call's totals). `<UsageChip>` rewritten:
  icon-led row with `8.2s · 3.2k tok · $0.0084 · 3 tools` shown
  for every finalized assistant message.
- **POL-D.** `<FileChips>` overflow: `maxVisible` (default 3) +
  `onShowAll` callback. Failed-parse files pin to the front of
  the visible window so retries stay reachable. Long lists
  collapse to "+N more" that opens the document explorer.
- **POL-G.** Tool transparency: `<ToolCallBlock>` summary row
  always shows the tool name + a 1-line result preview
  (`kaos-source-fr-search → 12 results: [...]`). New `defaultOpen`
  prop drives expansion; `<Message>` sets it for streaming /
  running / error states. A consumer-driven `verboseTools` flag
  (typically a header toggle) overrides to keep ALL tool blocks
  expanded in the transcript.
- **POL-C (companion).** `<DocumentExplorer>` panel: right rail
  listing every uploaded file as a collapsible card (filename,
  size, content type, token count, parse status, LLM summary in
  the body).

### Fixed

- **`splitting: true` in tsup** — multi-entry packages with shared
  module state (`createContext`) duplicate the module across entry
  bundles by default. Without `splitting`, the
  `<KaosUIProvider>` (from `/lib`) wrote into one `TransportContext`
  instance and `useSendMessage` (from `/hooks`) read from another
  — manifesting as `useTransport(): no <KaosUIProvider> in tree`
  even when correctly wrapped. tsup now hoists shared modules into
  `dist/chunk-*.js`.
- **`transportFetch` content-type** — drop the default
  `application/json` when `init.body instanceof FormData` so the
  browser sets `multipart/form-data; boundary=…` itself. Without
  this, file uploads errored with FastAPI 422 (missing form field).
- **`<DocumentExplorer>` Backfill action** — when any file is
  missing `token_count` or `summary`, the panel header surfaces a
  Backfill button that drives the new `useBackfillFiles` mutation.
  Pre-existing files (uploaded before the enrichment pipeline
  shipped) can be repaired without re-upload.

### Renamed

- `TurnStatus` discriminator union type → `TurnStatusKind` to
  avoid a name collision with the `<TurnStatus>` component at
  the root barrel.

### Dependencies

- Add: `markdown-it ^14.1.0`, `eventsource-parser ^3.0.0`,
  `lucide-react ^0.510.0`.
- Drop: `marked`, `dompurify`. markdown-it gives us the
  `validateLink` whitelist hook in one library.

[0.1.0-alpha.0]: https://github.com/273v/kaos-ui/releases/tag/kaos-ui-react%400.1.0-alpha.0
