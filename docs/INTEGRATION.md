# kaos-ui Integration Guide

> How every kaos-ui template plugs into the KAOS ecosystem. This is the
> contract every template implements. Per-template specs live in
> `docs/templates/`. Deployment-specific notes live in `docs/DEPLOYMENT.md`.

## 0. Template variables (substitution placeholders)

The scaffolder substitutes these in every text file (`{{KAOS_*}}`)
and in path components (so `{{KAOS_PYTHON_MODULE}}/settings.py.tmpl`
becomes `<slug>/settings.py`):

| Variable | Example for ``"My App"`` | Use |
|---|---|---|
| `KAOS_PROJECT_NAME` | `My App` | Display strings, README titles, page titles |
| `KAOS_PROJECT_SLUG` | `my_app` | Underscored Python-friendly slug |
| `KAOS_PYTHON_MODULE` | `my_app` | Python package name (same as slug) |
| `KAOS_NPM_SLUG` | `my-app` | Hyphenated npm-friendly slug; use for npm scope/package names |
| `KAOS_PYTHON_VERSION` | `3.14` | For `.python-version`, Dockerfile ARG |
| `KAOS_NODE_VERSION` | `24` | For frontend |
| `KAOS_TEMPLATE` | `web:spa` | The kind that scaffolded this project |

Critical: use `KAOS_NPM_SLUG` (not `KAOS_PROJECT_SLUG`) for npm
scope names. pnpm rejects underscores in workspace package names —
`@my_app/ui` would not resolve.

## 1. The startup dance

Every Python entrypoint in a kaos-ui template — Streamlit `app.py`,
Textual `app.py`, FastAPI `main.py` — performs the same sequence at
startup:

```python
from kaos_core import KaosRuntime, register_core_tools
from kaos_core.logging import get_logger

from {slug}.settings import AppSettings

settings = AppSettings()                        # env_prefix="APP_"; SecretStr keys
logger = get_logger("kaos.app.{slug}")          # structured, kaos.* hierarchy
runtime = KaosRuntime()                         # the bus
register_core_tools(runtime)                    # kaos-core tools
# kind-specific extras (kaos-pdf, kaos-office, kaos-agents, ...) registered here
```

This gives the vibe coder (and the agent editing the code) one
consistent set of primitives — runtime, settings, logging, errors —
across all three templates. Adding a tool to the agent or a route to
the API uses the same patterns regardless of which form factor was
picked.

## 2. KAOS modules per template

| Template | Required | Optional (extras) |
|---|---|---|
| `dashboard:streamlit` | `kaos-core`, `kaos-content[markdown,nlp]`, `kaos-agents`, `kaos-llm-client`, `kaos-pdf`, `kaos-office` | `kaos-tabular`, `kaos-citations`, `kaos-source` |
| `tui:textual` | `kaos-core`, `kaos-agents`, `kaos-content[markdown]`, `kaos-llm-client` | `kaos-pdf`, `kaos-office` |
| `web:spa` (fullstack) | backend: `kaos-core`, `kaos-agents`, `kaos-content`, `kaos-llm-client`, `kaos-pdf`, `kaos-office`. frontend: Vite + React 19 + TanStack + Tailwind v4 + shadcn + Zod | `kaos-tabular`, `kaos-citations` |

Every template's `pyproject.toml.tmpl` pins major versions and uses
KAOS module extras (`kaos-content[markdown,nlp]`) — never the bare
package, so `[nlp]` BM25 and `[markdown]` round-trip ship by default.

## 3. Settings contract

Every scaffolded project ships an `AppSettings` class:

```python
from kaos_core.config import ModuleSettings
from pydantic import SecretStr, model_validator
from pydantic_settings import SettingsConfigDict

class AppSettings(ModuleSettings):
    auth_token: SecretStr | None = None      # required at runtime; see auth contract
    env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    vfs_path: Path = Path(".kaos-vfs")
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_types: tuple[str, ...] = ("pdf", "docx", "pptx", "xlsx", "csv", "txt", "md")
    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-4-5"

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        # If the backend lives in a subdir (web:spa: backend/), try
        # project-root .env first then backend-local. Streamlit /
        # Textual put their entrypoints at root and use just ".env".
        env_file=("../.env", ".env"),
        extra="ignore",
    )

    @model_validator(mode="after")
    def _refuse_to_start_without_auth_token(self) -> "AppSettings":
        if self.env != "test" and not self.auth_token:
            raise RuntimeError(
                "APP_AUTH_TOKEN is not set.\n"
                "How to fix: cp .env.example .env, then edit .env and set "
                "APP_AUTH_TOKEN to a long random string.\n"
                "Alternative: set ENV=test for unit tests."
            )
        return self
```

Rules:

- **`env_prefix="APP_"`** — the scaffold-local prefix. KAOS modules
  inside the scaffold (kaos-pdf, kaos-web, kaos-llm-client, …) keep
  their own `KAOS_*` prefixes — settings cascade.
- **`SecretStr` for every key/token/password.** Auto-redacted in logs,
  in the Settings page, in error messages.
- **`extra="ignore"`** so adding new env vars never breaks an existing
  deploy.
- **`mode="after"` validator** for cross-field rules like the
  refuse-to-start-without-auth-token check. (Legacy fallbacks still use
  `mode="before"` per the top-level `CLAUDE.md`.)
- **The app refuses to start** if a required secret is missing in any
  non-test environment.
- **`env_file=("../.env", ".env")`** for backends that live in a
  subdir. pydantic-settings reads the first existing file. Without
  this, `cd backend && uvicorn` won't find a project-root `.env`.
  See `PATTERNS.md` § Settings.

### Tuple env vars: `Annotated[..., NoDecode]` + CSV parser

For tuple-typed fields like `cors_origins`:

```python
from pydantic_settings import NoDecode

class AppSettings(ModuleSettings):
    cors_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:5173",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(s.strip() for s in value.split(",") if s.strip())
        return value
```

Without `NoDecode`, pydantic-settings tries to JSON-parse env strings
into tuples — a vibe coder typing `APP_CORS_ORIGINS=https://a,https://b`
gets `JSONDecodeError`. With it, the validator splits CSV input.

## 4. Auth contract

Single bearer token, set in `.env` as `APP_AUTH_TOKEN`. Three reasons
this is the default:

1. **Zero infrastructure.** No password DB, no email provider, no OAuth
   app registration. The vibe coder is up and running in seconds.
2. **Sandboxed by default.** Localhost-only bind + bearer token means
   nothing is publicly reachable until the vibe coder explicitly opens
   it up.
3. **Production swap path is documented.** Each template's `CLAUDE.md`
   has a section on swapping bearer for OAuth/OIDC, with the exact
   files to edit.

Token storage:

| Surface | Storage |
|---|---|
| Streamlit | `st.session_state["auth"]` after login page submission |
| Textual | N/A — single-user terminal app, auth not relevant |
| Web SPA | `httpOnly` cookie set by login endpoint. Backend middleware reads it on `/v1/*` |

CSRF: bearer-only flows are immune. If the vibe coder swaps to
cookie+session auth in production, the template's `CLAUDE.md` flags
the additional CSRF middleware to wire in.

## 5. Logging contract

```python
from kaos_core.logging import get_logger
logger = get_logger("kaos.app.{slug}")
```

- Always use `kaos_core.logging.get_logger` — never `logging.getLogger`.
- Logger name follows `kaos.app.{slug}.{module}` for subsystems.
- JSON output when `ENV=production`. Human-readable in dev/test.
- Auto-includes `session_id` and `trace_id` when a `KaosContext` is in
  scope (FastAPI: per-request middleware sets it; Streamlit: per
  session; Textual: per chat session).

## 6. Error contract

Each scaffold defines a per-app exception base:

```python
class {Slug}Error(KaosCoreError):
    """Base for app-level errors."""
```

Every user-facing surface (CLI, API responses, Streamlit pages,
Textual screens) translates exceptions into the agent-friendly shape:

```json
{"what": "...", "how_to_fix": "...", "alternative_tool": "..."}
```

Stack traces never leak to end users. Internal logs keep them.

## 7. VFS / artifacts

- Default VFS path: `./.kaos-vfs/` (relative to project root). Override
  via `APP_VFS_PATH`.
- Session memory, uploaded documents, search indexes, chat history —
  all in VFS.
- Production deploys mount `./.kaos-vfs/` as a volume in
  `docker-compose.yml`.
- VFS is disk-first per the top-level KAOS principle. Range reads,
  pagination, lazy loading available via the `kaos-core` VFS API.

## 8. File upload contract

| Setting | Default | Override |
|---|---|---|
| Max size | 25 MB | `APP_MAX_UPLOAD_BYTES` |
| Allowed types | `pdf, docx, pptx, xlsx, csv, txt, md` | `APP_ALLOWED_UPLOAD_TYPES` (comma-separated) |
| Filename sanitization | slugified, original kept in metadata | — |
| Storage | VFS at `documents/{uuid}/` | — |
| Parsing | routed by extension to `kaos-pdf` / `kaos-office` | — |

## 9. Database

- **SQLite by default** at `./.kaos-vfs/app.db`. Zero-config.
- **Postgres path**: `docker-compose.postgres.yml` overlay activates a
  Postgres service; the app reads `APP_DATABASE_URL` if set.
- **SQLAlchemy 2.x** with `async_session_maker` for any non-trivial
  state.
- **Alembic** wired with one initial migration; subsequent migrations
  generated via `make db:revision`.

## 10. Cross-cutting safety defaults

| Concern | Default |
|---|---|
| `.env` missing | App refuses to start with `how_to_fix: cp .env.example .env` |
| Bind | `127.0.0.1` only. Public bind requires explicit `--host 0.0.0.0` |
| `DEBUG=True` in prod | `AppSettings` validator refuses to load |
| Weak token in prod | Validator rejects `changeme` / `password` / `admin` / `dev` / `test` and tokens shorter than 32 chars |
| Wildcard CORS in prod | Validator rejects `APP_CORS_ORIGINS=*` (browsers reject wildcard with credentials anyway) |
| Cookie `Secure` flag | `secure = (env == "production")` — dev/test speak http, prod gets the flag |
| `Origin` header | State-changing methods (POST/PUT/PATCH/DELETE) require `Origin` to be in `APP_CORS_ORIGINS` (belt-and-suspenders CSRF for the SPA backend) |
| Magic-byte uploads | `python-magic` verifies content type matches declared extension; falls back to a logged warning when libmagic missing |
| Container | Multi-stage, non-root (`uid=1000`), slim base, `HEALTHCHECK`, no secrets baked |
| Pre-commit | `ruff` + `ty` + `eslint` (web only) + `gitleaks` |
| Errors at boundaries | `what / how_to_fix / alternative` shape |
| Make verbs (uniform) | `install dev test up down doctor build typecheck` |
| Logging in prod | JSON output, `ENV=production` triggers |
| CWE-117 | CR/LF stripped from logged user-controlled values |
| Secrets in logs | `SecretStr` auto-redacts; never `print(settings.dict())` — use `model_dump_redacted()` |
| `_HumanFormatter` | Clears `record.args = ()` after substitution. See PATTERNS.md § Logging |

## 10a. Lazy KAOS imports in service modules

Every `services/*.py` lazy-imports optional KAOS extras (kaos-agents,
kaos-content, kaos-pdf, kaos-office). Pattern:

```python
def build_runner(settings, runtime):
    from kaos_agents import Agent, AgentPattern, Runner   # ← inside the function
    return Runner(Agent(...), runtime=runtime)
```

This means a screen / page / route can `from {slug}.services import
chat as chat_service` cheaply — only when a user actually calls
`build_runner(...)` does the heavy import fire. The minimal-deps
integration tests rely on this; production deploys should have the
full kaos-* stack installed.

## 11. Agent affordances inside scaffolded projects

Every template ships with:

- A `CLAUDE.md` listing files-the-agent-must-not-edit (lockfiles,
  generated migrations, `.env`).
- An `AGENTS.md` with cross-tool guidance (Codex, Gemini).
- Each subsystem (`{slug}/services/*.py`) has a one-line module
  docstring naming its purpose, so the agent can grep its way around.
- Routes/pages annotated with comments saying which `KaosTool` to call
  for each operation.
- A `make doctor` target the agent can run to validate its edits.

## 12. References

- Top-level `CLAUDE.md` — KAOS conventions (settings hierarchy, no
  AGPL, structured logging, etc.)
- `docs/guides/code-quality.md` — the QA gate every scaffold must pass
- `docs/guides/cli-standard.md` — CLI conventions (consumed by
  `kaos-ui` itself, not the scaffolds)
- `docs/guides/tool-design.md` — MCP tool design (consumed by Phase 2
  tools)
- `docs/guides/mcp-data-flow.md` — large outputs by handle, not value
- `kaos-ui/docs/SAFETY.md` — the per-template safe-by-default contract
- `kaos-ui/docs/templates/*.md` — per-template specifications
