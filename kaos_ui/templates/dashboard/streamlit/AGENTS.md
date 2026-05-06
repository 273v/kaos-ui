# {{KAOS_PROJECT_NAME}} — Cross-tool Agent Notes

The detailed runbook lives in `CLAUDE.md`. This file is a one-page
orientation for any agent (Codex CLI, Gemini CLI, Cursor, Windsurf)
walking into the project cold.

## Two-minute orientation

1. **Read `CLAUDE.md`.** It has the full runbook: never-edit files,
   how-to-add-X examples, troubleshooting, before-commit checklist.
2. **Run `make doctor`.** Read its output before editing anything.
3. **Project shape:**
   - `app.py` — entry, builds the runtime, registers pages via `st.navigation`.
   - `pages/*.py` — one file per page. Calls `auth.require(settings)` first.
   - `{{KAOS_PYTHON_MODULE}}/settings.py` — pydantic `AppSettings`. All config flows through here.
   - `{{KAOS_PYTHON_MODULE}}/runtime.py` — `KaosRuntime` factory.
   - `{{KAOS_PYTHON_MODULE}}/auth.py` — token gate.
   - `{{KAOS_PYTHON_MODULE}}/services/*.py` — business logic (chat, uploads, search, documents).
   - `tests/*.py` — pytest. Run with `make test`.
4. **Make the smallest change that solves the task.**
5. **Run `make test` AND `make typecheck` before declaring done.**

## What you MUST NOT do (subset of CLAUDE.md)

- Edit `uv.lock`, `.env`, `.streamlit/config.toml`, `Dockerfile`'s
  non-root setup, or remove any line from `.gitignore`.
- Read `os.environ` directly inside services or pages (use `AppSettings`).
- Catch a broad `Exception` without logging it (use a typed `AppError`).
- Skip `auth.require(settings)` in a new page.
- Set `APP_DEBUG=true` in `.env` when `APP_ENV=production` (the app
  refuses to start anyway, but don't waste time trying).

## Common tasks → the right place

- "Add a page that shows X" → new file in `pages/`, register in
  `app.py`. CLAUDE.md has a worked example.
- "Wire the chat to use a different model" → edit
  `APP_LLM_PROVIDER` / `APP_LLM_MODEL` in `.env`, NOT the hardcoded
  defaults in `settings.py`.
- "Add an upload type" → extend `APP_ALLOWED_UPLOAD_TYPES` in `.env`
  AND add the new MIME mapping to `_EXTENSION_TO_MIME` in
  `services/uploads.py`. Magic-byte check requires both.
- "Wire OIDC instead of bearer" → CLAUDE.md § Auth swap path.

## When stuck

- Doctor's `what / how_to_fix / alternative_tool` output is the
  authoritative guidance — paste it back to the user if you can't act
  on it directly.
- The CLAUDE.md Troubleshooting table covers the common failure modes.
- The kaos-ui repo's `docs/PATTERNS.md` documents subtle gotchas
  (LogRecord reserved keys, `_env_file=None` in tests, AppTest +
  `st.navigation` gap).
