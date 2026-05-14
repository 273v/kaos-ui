# single-user-chat

> **Status: planning.** Code is not yet written. See `docs/` for requirements, architecture, and the implementation plan.

A pre-built reference application demonstrating how to build a single-user agentic chat experience on top of `kaos-agents`, reusing the design system and SSE plumbing from the `kaos-ui` `web:spa` scaffold.

This is not a template. It is documentation-by-code — a working app that vibe coders clone and humans-or-agents read as the canonical "how the pieces fit together" example.

## What's here

```
single-user-chat/
├── README.md             ← you are here
└── docs/
    ├── PRD.md            ← product requirements: problem, audience, goals, non-goals
    ├── ARCHITECTURE.md   ← system design: components, API contract, event handling
    ├── UX-LANGUAGE.md    ← visual + interaction spec (competitor-informed)
    └── PLAN.md           ← phased implementation plan + test gates
```

The plan has been verified against real PyPI installs of `kaos-agents==0.1.0a1`, `kaos-core==0.1.0a6`, `kaos-llm-client==0.1.0a3` (the kaos-* packages now ship on PyPI) and against competitor chat UX (Harvey, Legora, Midpage, Mike, Claude.ai). Key load-bearing decisions:

- **Backend = `kaos_agents.api.server.create_app()` + a thin extension layer** for `/v1/models` and `/v1/chat/*`. Most session routes ship upstream — we don't reimplement.
- **`packages/ui` is synced at install time** from the `web:spa` template via `scripts/sync-ui.sh`, with placeholders rendered.
- **Visual language is editorial-legal**, not consumer-SaaS — see `UX-LANGUAGE.md` for the explicit anti-pattern list.

## What it will do (v1)

- Multi-turn chat with conversation persistence across page reloads
- Multi-session: session list sidebar, "New chat" button, rename, delete, export
- Model picker (Claude / GPT / Gemini / Grok current-generation models)
- Per-session editable system prompt
- Full kaos-agents event surface — every event type renders something
- Same `packages/ui`, same design tokens, same Caddyfile, same auth pattern as the `web:spa` scaffold

## What it will not do

- Multi-user / OIDC (bearer-token-from-env only)
- Tool-call approval UI (auto-allow read-only, reject everything else)
- RAG corpus management
- PyPI distribution (lives in the git repo as a reference)

See `docs/PRD.md` § Non-goals for the full list.

## How to read these docs

Top-down, in order:

1. **`docs/PRD.md`** — what we're building and why.
2. **`docs/ARCHITECTURE.md`** — how the components fit, with file-level layout and the API contract.
3. **`docs/PLAN.md`** — phased implementation with concrete deliverables per phase and test gates.

When code lands here, it will follow the structure described in `docs/ARCHITECTURE.md`.
