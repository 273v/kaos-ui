# {{KAOS_PROJECT_NAME}} — Cross-tool Agent Notes

The detailed runbook lives in `CLAUDE.md`. This file is a one-page
orientation for any agent (Codex CLI, Gemini CLI, Cursor) walking in
cold.

## Two-minute orientation

1. **Read `CLAUDE.md`** for the full runbook.
2. **Run `make doctor`.** Read its output before editing.
3. **Project shape:**
   - `{{KAOS_PYTHON_MODULE}}/app.py` — Textual `App` with key bindings + screen registry.
   - `{{KAOS_PYTHON_MODULE}}/screens/*.py` — one file per screen (Chat / Documents / Settings).
   - `{{KAOS_PYTHON_MODULE}}/services/*.py` — business logic (chat, documents). Heavy KAOS imports are lazy.
   - `{{KAOS_PYTHON_MODULE}}/settings.py` — pydantic `AppSettings`. All config flows through here.
   - `{{KAOS_PYTHON_MODULE}}/runtime.py` — `KaosRuntime` factory.
   - `{{KAOS_PYTHON_MODULE}}/styles.tcss` — Textual CSS theming.
   - `tests/*.py` — pytest. Run with `make test`.
4. **Make the smallest change that solves the task.**
5. **Run `make test` AND `make typecheck` before declaring done.**

## Rules of thumb

- Heavy ops (LLM streaming) belong in `@work` workers, NOT in the main
  event loop. Blocking the main loop freezes the UI.
- Logging goes through `kaos_core.logging.get_logger` — never `print()`
  while the app is running (Textual owns stdout).
- Settings are read once at app startup; changes need a restart.
- New screens go in `{{KAOS_PYTHON_MODULE}}/screens/<name>.py` AND
  registered in `app.py`'s `SCREENS` dict + `BINDINGS`.
- `tests/test_smoke.py::PAGE_PATHS` lists every screen — keep updated.

## When stuck

- `make doctor` output is authoritative — paste it back to the user if
  unclear.
- `CLAUDE.md` Troubleshooting table covers common failures.
- `kaos-ui/docs/PATTERNS.md` documents subtle gotchas across templates.
