# {{KAOS_PROJECT_NAME}} — Agent Runbook

> Read this BEFORE editing anything in this project. Rules for an LLM
> agent (Claude Code, Codex, Gemini) working inside this scaffold.

## What this project is

A Streamlit dashboard scaffolded by `kaos-ui new dashboard`. Backend
logic runs on `kaos-core` runtime + KAOS modules (`kaos-agents` for
chat, `kaos-content` for documents, `kaos-pdf`/`kaos-office` for
parsing, `kaos-llm-client` for provider transport). Pages are thin —
they bind UI controls to functions in `{{KAOS_PYTHON_MODULE}}/services/`.

## Files NEVER edit (auto-managed)

- `uv.lock`                                  — managed by `uv sync`
- `.venv/`, `__pycache__/`, build artifacts  — generated
- `.env`                                     — secrets the user owns
- `.gitignore`                               — already correct; adding to it is fine, removing entries is not
- `pyproject.toml [build-system]`            — packaging metadata
- `pyproject.toml [tool.hatch.*]`            — packaging metadata
- `Dockerfile` (non-root user, healthcheck)  — security-load-bearing
- `.streamlit/config.toml`                   — security-hardened defaults

If you think one of these MUST change, stop and ask the user.

## Files that DO need updating when you add features

| Adding | Goes in | Don't forget |
|---|---|---|
| A new page | `pages/<name>.py` + register in `app.py`'s `st.navigation()` | `tests/test_smoke.py` page list |
| A new service / business logic | `{{KAOS_PYTHON_MODULE}}/services/<name>.py` | one focused unit test |
| A new setting | `{{KAOS_PYTHON_MODULE}}/settings.py` (`AppSettings`) | `.env.example` + docstring + redaction if `SecretStr` |
| A new exception type | `{{KAOS_PYTHON_MODULE}}/exceptions.py` (subclass `AppError`) | what / how_to_fix / alternative shape |
| A new dependency | `pyproject.toml [project.dependencies]` | run `uv lock`, then `uv sync` |

## How to add a new page (worked example)

```bash
# 1. Create the file
touch pages/reports.py
```

```python
# pages/reports.py
"""Reports page — example."""

from __future__ import annotations

import streamlit as st

from {{KAOS_PYTHON_MODULE}} import auth
from {{KAOS_PYTHON_MODULE}}.settings import AppSettings

settings: AppSettings = st.session_state["settings"]
auth.require(settings)            # ← mandatory first line

st.title("Reports")
# ... your UI here ...
```

```python
# app.py — add to the pages list inside main():
pages = [
    st.Page("pages/chat.py", title="Chat", icon=":material/chat:", default=True),
    # ...
    st.Page("pages/reports.py", title="Reports", icon=":material/analytics:"),
]
```

```python
# tests/test_smoke.py — add to PAGE_PATHS:
PAGE_PATHS = (
    "pages/chat.py",
    # ...
    "pages/reports.py",
)
```

Run `make test` to confirm it boots.

## How to add a new service

```python
# {{KAOS_PYTHON_MODULE}}/services/reports.py
"""Reports service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from {{KAOS_PYTHON_MODULE}}.exceptions import AppError
from {{KAOS_PYTHON_MODULE}}.logging_setup import app_logger

if TYPE_CHECKING:
    from {{KAOS_PYTHON_MODULE}}.settings import AppSettings

logger = app_logger("reports")


@dataclass(frozen=True, slots=True)
class Report:
    name: str
    rows: int


def list_reports(settings: AppSettings) -> list[Report]:
    """One-line summary."""
    # ... real logic ...
    return []
```

Add `tests/test_reports.py` mirroring `test_uploads.py`.

## How to add a new setting

```python
# {{KAOS_PYTHON_MODULE}}/settings.py — inside AppSettings:
class AppSettings(ModuleSettings):
    # ... existing fields ...

    # New field — pick a sensible default + document with a comment.
    reports_enabled: bool = True

    # If it's a secret, use SecretStr — model_dump_redacted picks it up
    # automatically.
    new_api_key: SecretStr | None = None
```

```bash
# .env.example — add the corresponding env var
APP_REPORTS_ENABLED=true
APP_NEW_API_KEY=
```

If the setting is required in production, add a clause to the
`_validate_security_invariants` validator with the
`what / how_to_fix / alternative` error message.

## Conventions inside this project

- **Auth**: every page calls `auth.require(settings)` before rendering.
- **Settings**: never read `os.environ` directly. Pull from
  `st.session_state["settings"]`.
- **Logging**: use `kaos_core.logging.get_logger("kaos.app.{{KAOS_PROJECT_SLUG}}.<sub>")`
  via the helper `app_logger("<sub>")`.
- **Errors**: raise subclasses of `AppError`, never bare `Exception`.
  Every error message has `what / how_to_fix / alternative` keys (or
  natural-language equivalents).
- **Heavy ops**: don't block the Streamlit event loop with synchronous
  LLM calls in page code. The chat page uses `asyncio.run()` — fine for
  single-user. For multi-user, queue the work.
- **Caches**: `@st.cache_resource` and `@st.cache_data` MUST take
  explicit `ttl=` and `max_entries=`. Unbounded caches OOM.
- **Secrets**: `SecretStr` for everything; `.get_secret_value()` only at
  the wire boundary. Never log secrets.
- **Uploads**: server-side `validate()` (size + extension allowlist +
  magic bytes) BEFORE any parser sees the bytes.

## Production deployment checklist

Before `docker compose up` on a public host:

- [ ] `APP_ENV=production` set in `.env`
- [ ] `APP_AUTH_TOKEN` is random and ≥ 32 chars (settings will refuse weak ones)
- [ ] `APP_DEBUG=false` (settings will refuse `true` in prod)
- [ ] LLM API key set for `APP_LLM_PROVIDER`
- [ ] Reverse proxy (Caddy/nginx) terminates TLS and injects security headers
- [ ] Bind is `127.0.0.1:8501` (compose default); proxy fronts it
- [ ] `make doctor` exits 0
- [ ] `make test` passes

## Auth swap path: bearer → OIDC / OAuth

The default bearer-from-`.env` is suitable for a single-team internal
dashboard reachable only over a VPN or behind a reverse proxy. For
public-internet deployment, swap to OIDC:

1. **Streamlit native** (recommended, ≥1.42): use `st.login()` with an
   OIDC provider (Google, Microsoft, Okta, Auth0). Add `[auth]` block
   to `.streamlit/secrets.toml`:
   ```toml
   [auth]
   redirect_uri = "https://your-domain/oauth2callback"
   cookie_secret = "<run: head -c 32 /dev/urandom | base64>"
   client_id = "..."
   client_secret = "..."
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
2. Replace the body of `auth.require()` with `if not st.experimental_user.is_logged_in: st.login()`.
3. Remove `APP_AUTH_TOKEN` from `.env.example` (the validator stops
   requiring it once you've replaced `auth.require`).
4. Update `tests/test_auth.py` to monkeypatch `st.experimental_user`.

Alternative: front Streamlit with Caddy + `forward_auth` to an OIDC
proxy (`oauth2-proxy`) — Streamlit sees only the proxy and trusts the
`X-Forwarded-Email` header.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `SettingsError: APP_AUTH_TOKEN is not set` at startup | `cp .env.example .env`, then edit and set `APP_AUTH_TOKEN` |
| `SettingsError: ... is too short for production` | Token must be ≥32 chars. Regenerate: `head -c 32 /dev/urandom \| base64` |
| `KeyError: "Attempt to overwrite 'X' in LogRecord"` | `extra={"X": ...}` collides with a reserved LogRecord field. Rename. See kaos-ui PATTERNS.md §Logging |
| `RuntimeError: APP_AUTH_TOKEN ...` only in tests | Tests must construct `AppSettings(_env_file=None)` to ignore the project's `.env` |
| `streamlit.errors.Error: ... AppTest does not render page` | Known: AppTest + `st.navigation` gap. Test pages individually via `AppTest.from_file("pages/foo.py")`. See kaos-ui PATTERNS.md §Streamlit |
| Upload rejected with "content does not match declared extension" | The file's actual content doesn't match its extension. This is the magic-byte check working as intended |
| `make doctor` fails on `python-magic` import | Install `libmagic1` (Linux) / `libmagic` (macOS via Homebrew). Without it, magic-byte check downgrades to a logged warning |

## Before-commit checklist

- [ ] `make format` (ruff format)
- [ ] `make lint` (ruff check)
- [ ] `make typecheck` (ty)
- [ ] `make test` — all green
- [ ] `make doctor` — exits 0
- [ ] No secrets in the diff (`git diff` then `gitleaks detect --staged`)
- [ ] `.env` not staged (`git diff --cached --name-only | grep -v '^\.env$'`)

## Required checklists (KAOS top-level)

Apply these from the kaos-modules `docs/python/checklists/` directory
to every change:

- 03-implement, 04-test, 05-quality, 07-commit

## Local dev with kaos-modules workspace

If you scaffolded this inside the `kaos-modules` workspace (i.e., the
KAOS packages aren't on PyPI yet), append the following to
`pyproject.toml` so `uv sync` resolves them locally:

```toml
[tool.uv.sources]
kaos-core      = { path = "../kaos-core",      editable = true }
kaos-content   = { path = "../kaos-content",   editable = true }
kaos-agents    = { path = "../kaos-agents",    editable = true }
kaos-llm-client = { path = "../kaos-llm-client", editable = true }
kaos-pdf       = { path = "../kaos-pdf",       editable = true }
kaos-office    = { path = "../kaos-office",    editable = true }
```

Adjust the relative paths to match where your scaffolded project sits.
Once kaos-* are on PyPI, this entire block disappears.
