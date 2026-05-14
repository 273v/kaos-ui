# E2E smoke procedure

This is the manual smoke-test runbook contributors should walk
before signing off on chat-surface PRs. Each step lists what to do
and the observable signal that it worked.

Two ways to run it:

- **Chrome DevTools MCP** (inside Claude Code): the snapshot/click
  tools translate each step into reproducible actions. See
  `docs/CONTRIBUTING.md` for the wrapper that gets the MCP onto
  your X display.
- **Manual browser**: open http://localhost:5173/ after `make dev-bg`
  and click through the same flow.

A Playwright spec covering this same path is tracked under task
TST-4-playwright — currently a follow-up, not in this batch
because the Playwright binary download is ~120MB and we want the
manual procedure documented first.

## Prerequisites

```bash
cd examples/single-user-chat
make dev-bg
# → backend on :8000, spa on :5173, token printed
```

Optional: set `SIMULATOR_ANTHROPIC_API_KEY` so the LLM-dependent
steps work end-to-end. Without it, the summarizer + auto-titler +
chat itself fail silently (logged WARNING).

## Steps

### 1. Login + session list renders

1. Open http://localhost:5173/
2. Paste the dev token from `make dev-bg` output
3. Click **Sign in**

✅ Expected: redirect to `/sessions`, sidebar lists prior sessions
with title + message-count pill, sort dropdown shows "Last used".

### 2. Sidebar UX (POL-D)

1. Hover any row → `…` menu appears
2. Click `…` → **Rename** menu item visible
3. Click **Rename** → input replaces the title with the current
   title preselected
4. Type a new name, hit **Enter**

✅ Expected: title updates immediately, sidebar refreshes.

5. Click the star icon on a different row

✅ Expected: star fills with the warn color. Select "Starred first"
in the sort dropdown — that row moves to the top.

### 3. Chat detail + chips (POL-F)

1. Click into a session that has uploaded files (or upload 4+ files
   into a new session)
2. Look at the chip row above the composer

✅ Expected: at most 3 file chips visible + a "Show N more files"
pill. Failed-parse files (if any) pin to the front of the visible
window.

3. Click the "+N more" pill

✅ Expected: documents panel opens on the right side.

### 4. DocumentExplorer + Backfill (POL-C + FIX-2)

1. With the panel open, click any file card

✅ Expected: card expands to show the LLM summary in italic + the
parse status. If the summary is null, the panel offers the
**Backfill** button in the header.

2. If files are missing summaries, click **Backfill** in the
   header

✅ Expected: spinner replaces the icon, button disables, then the
file list re-renders with summaries populated.

### 5. Live chat with tools (POL-E + FIX-1 + POL-G)

1. Send a message that needs a tool: "search the federal register
   for cheese regulations"
2. Watch the streaming response

✅ Expected:
- `<TurnStatus>` cycles: thinking → tool name → idle
- Tool-call cards render inline under the assistant message with
  the 1-line result preview visible
- `<UsageChip>` lands at the end of the turn with latency / tokens
  / cost / N tools

### 6. Verbose tools toggle (POL-G)

1. Click the Wrench icon in the header

✅ Expected: aria-pressed flips to `true`, button gains a muted
background. Every tool-call card in the transcript expands to
show full args + full result_preview.

2. Reload the page (testing FIX-1 hydration)

✅ Expected: prior assistant messages still show the tool-call
cards from `sessions/{id}/toolcalls/turn-N.jsonl`. Toggling Wrench
expands them. If the cards are missing entirely on reload, FIX-1
regressed.

### 7. Citations panel (P2-1)

1. Send "what is 17 CFR 240.10b-5 about?"
2. After the response lands, click the Quote icon in the header

✅ Expected: panel opens, shows ≥1 citation grouped under "CFR" with
the normalized form + the raw substring.

### 8. Run inspector (POL-C debug)

1. Click the Bug icon in the header (or append `?debug=true`)

✅ Expected: bottom-right rail shows live $ / tokens / N events,
category filter chips, scrollable event log. Clicking any event
row expands a JsonTree of the raw payload.

### 9. Stop

```bash
make stop
```

✅ Expected: both ports clear.

## Known issues this procedure DOES NOT cover

- Multi-user concurrency (only single-user-chat ships today)
- Long-running streams (test up to ~30s; longer SSE behavior is
  flaky in some browsers due to proxy timeouts)
- Drag-drop overlay (Chrome DevTools MCP can't synthesize a
  dataTransfer.files payload; manual browser only)

## Recording a failure

If a step fails, capture:

1. The MCP `take_snapshot` output (or a screenshot)
2. `make logs` (last ~50 lines of backend + spa)
3. Browser console errors (Chrome DevTools panel)
4. The exact step number that broke

Open a GitHub issue against the consuming app's repo (this
example, or your downstream consumer) and tag the relevant
`@273v/kaos-ui-react` task in the description.
