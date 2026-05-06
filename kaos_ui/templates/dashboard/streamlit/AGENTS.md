# {{KAOS_PROJECT_NAME}} — cross-tool agent notes

The same guidance as `CLAUDE.md`, applicable to Codex CLI, Gemini CLI,
and any other agentic coding tool that drops into this project.

See `CLAUDE.md` for the full ruleset (files-never-edit, where-new-code-goes,
conventions, production auth swap path).

## Quick orientation for an agent walking in cold

1. Run `make doctor` — read its output before editing anything.
2. The app is a Streamlit dashboard. Pages live in `pages/`. Business
   logic lives in `{{KAOS_PYTHON_MODULE}}/services/`.
3. Settings come from `AppSettings()` (pydantic-settings, prefix `APP_`).
4. The chat page uses `kaos-agents` Runner; SessionMemory is persisted
   to `.kaos-vfs/sessions/`.
5. Make the smallest change that solves the task. Run `make test` and
   `make typecheck` before declaring done.
