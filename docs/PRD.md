# kaos-ui Product Requirements

## 1. Problem

KAOS exposes 200+ MCP tools and a rich agentic runtime, but a non-developer who wants to ship a working application — a dashboard, a desktop tool, a web app — has to assemble the front-end and the deployment shape themselves. The agent guiding them is not currently equipped to scaffold a safe, runnable app from a single tool call. Templates exist (`kaos-mcp/kaos_mcp/management/templates/`) but are commingled with the MCP package, do not cover terminal or desktop form factors, and lack the safety guarantees a vibe coder needs.

## 2. Audience

Two primary users:

1. **Vibe coder** — a lawyer, analyst, or domain expert who can describe what they want but not how to build it. They drive an LLM agent. They never read a Dockerfile. They will deploy what the agent generates.
2. **AI agent** — Claude Code, Codex, Gemini, ChatGPT-via-MCP. Selects a template based on the user's intent, scaffolds, runs post-install, validates, then iterates inside the generated project.

Secondary user: KAOS engineers who maintain templates and CI gates.

## 3. Goals

| # | Goal | Acceptance |
|---|---|---|
| G1 | Single package owns all UI/UX scaffolds | `kaos-mcp/templates/` is empty; all UI/UX templates live in `kaos-ui` |
| G2 | Every form factor covered | TUI, desktop (×2), web SPA, web API, dashboard all scaffold and run from one CLI |
| G3 | Agent-drivable | Four MCP tools cover list, info, scaffold, doctor; all annotated; agent-friendly errors |
| G4 | Safe by default | Every generated app passes the SAFETY contract immediately after scaffold |
| G5 | Survives upgrades | Integration tests scaffold → install → build on every CI run; templates pinned to known-good major versions |
| G6 | One-command up | `make up` boots a generated app (with deps) on a vibe coder's machine |

## 4. Non-goals

- A new web framework, component library, or design system. Templates compose existing tools (Vite, React, Tailwind, shadcn, Streamlit, Textual, Tauri).
- Cloud deployment automation. Per-cloud recipes can live in template `Makefile`s; orchestration (`kaos deploy`) is out of scope.
- Hosting a registry of community templates. Phase 4 may revisit.
- Replacing `cookiecutter`, `create-next-app`, etc. for general use. kaos-ui targets KAOS-shaped applications specifically.

## 5. Success metrics

- **Time-to-first-run** for a vibe coder, measured from `kaos doctor` to a running scaffolded app, under 5 minutes for any kind on a clean machine (excluding network-bound installs).
- **Doctor-clean rate** — fraction of fresh scaffolds that pass `make doctor` immediately. Target 100%.
- **Agent success rate** — fraction of agent-driven `kaos-ui-scaffold` calls that produce a working app on first try (no human edits before `make up`). Target 95% across kinds.
- **Vulnerability load** — `trivy` scan of any generated Dockerfile returns zero high/critical findings against the pinned base. Target 100%.

## 6. Out-of-scope dependencies

This package depends on:

- `kaos-core` (runtime, settings, logging, KaosTool ABC)
- Permissive third-party tools listed under each template

It does **not** depend on:

- `kaos-mcp` at runtime (only at CI time, for streamable HTTP integration tests)
- Any AGPL/GPL package — the top-level `CLAUDE.md` rule applies
- Any commercial scaffolding service or hosted registry

## 7. Constraints

- Python 3.13+, targeting 3.14 default (matches platform).
- Node 24 / pnpm 9 for web kinds (matches platform).
- Rust 1.80+ for Tauri (matches `kaos-nlp-core`).
- All templates must build offline-friendly: no required network calls beyond the standard package install.
- All CLIs follow `docs/guides/cli-standard.md`. All MCP tools follow `docs/guides/tool-design.md`.
