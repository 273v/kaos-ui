# {{KAOS_PROJECT_NAME}} — Agent Notes

> Rules for an LLM agent (Claude Code, Codex, Gemini) editing inside this scaffold.

## What this project is

A Streamlit dashboard scaffolded by `kaos-ui new dashboard`. Backend
logic runs on `kaos-core` runtime + KAOS modules. Pages are thin —
business logic lives in `{{KAOS_PYTHON_MODULE}}/services/`.

## Files NEVER edit

- `uv.lock`                         — managed by uv
- `pyproject.toml [tool.hatch.*]`   — packaging metadata
- `.env`                            — secrets; the user owns this
- `.gitignore`                      — already correct
- `Dockerfile [non-root user, healthcheck]` — security-load-bearing

## Where new code goes

| Adding | Goes in |
|---|---|
| A new page | `pages/<name>.py` + register in `app.py`'s `st.navigation()` |
| A new service / business logic | `{{KAOS_PYTHON_MODULE}}/services/<name>.py` |
| A new setting | `{{KAOS_PYTHON_MODULE}}/settings.py` (`AppSettings`) + `.env.example` |
| A new exception type | `{{KAOS_PYTHON_MODULE}}/exceptions.py` (subclass `AppError`) |
| A new test | `tests/test_<name>.py` |

## Conventions inside this project

- All settings come from `AppSettings()`. Never read `os.environ` directly.
- All logging goes through `kaos_core.logging.get_logger("kaos.app.{{KAOS_PROJECT_SLUG}}.<module>")`.
- Errors raised inside services include `what`, `how_to_fix`, and (where applicable) `alternative_tool` keys in their message.
- Pages call `auth.require(settings)` as the first executable line — never skip this.
- The `KaosRuntime` is a Streamlit `@st.cache_resource` singleton built once at app start. Pull it from `st.session_state["runtime"]`.
- Heavy operations (LLM calls, document parses) run inside `kaos-agents` Runner or async tasks — never block the Streamlit event loop with synchronous LLM calls.

## Production auth swap path

The default auth is a single bearer token from `.env`. To move to OAuth:

1. Add `authlib` or `streamlit-authenticator` to `pyproject.toml`.
2. Replace `auth.require()` body with the OAuth callback flow.
3. Remove `APP_AUTH_TOKEN` from `.env.example`.
4. Update `tests/test_auth.py`.

## Local dev with kaos-modules workspace

If you scaffolded this inside the kaos-modules workspace (i.e., the
KAOS packages aren't on PyPI yet), append the following to
`pyproject.toml`:

```toml
[tool.uv.sources]
kaos-core = { path = "../../kaos-modules/kaos-core", editable = true }
kaos-content = { path = "../../kaos-modules/kaos-content", editable = true }
kaos-agents = { path = "../../kaos-modules/kaos-agents", editable = true }
kaos-llm-client = { path = "../../kaos-modules/kaos-llm-client", editable = true }
kaos-pdf = { path = "../../kaos-modules/kaos-pdf", editable = true }
kaos-office = { path = "../../kaos-modules/kaos-office", editable = true }
```

Adjust the relative paths to match where your scaffolded project sits.

## Required checklists

Apply these from `kaos-modules/docs/python/checklists/` before committing:

- 03-implement, 04-test, 05-quality, 07-commit
