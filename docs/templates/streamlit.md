# Template Spec: `dashboard:streamlit`

> A multipage Streamlit app with kaos-agents wired in by default. Five
> pages, single-token auth, SQLite + VFS for state, all KAOS-native.

## What the vibe coder gets

```bash
kaos-ui new dashboard my-board
cd my-board
make install         # uv sync + pre-commit install
make doctor          # exits 0 immediately
make dev             # streamlit on http://127.0.0.1:8501
```

Login page asks for `APP_AUTH_TOKEN` from `.env`. After login: Chat,
Upload, Search, Browse, Settings — all working, all wired through
`kaos-core` runtime, all calling real KAOS modules.

## Scaffolded layout

```
my-board/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version            # 3.14
├── .streamlit/
│   ├── config.toml            # hardened: runOnSave=false, fileWatcherType=none in prod
│   └── secrets.toml.example
├── app.py                     # entry: settings, runtime, auth gate, sidebar nav
├── pages/
│   ├── 1_💬_Chat.py
│   ├── 2_📤_Upload.py
│   ├── 3_🔍_Search.py
│   ├── 4_📚_Browse.py
│   └── 5_⚙_Settings.py
├── {slug}/                    # the project's own python package
│   ├── __init__.py
│   ├── settings.py            # AppSettings(ModuleSettings)
│   ├── runtime.py             # build_runtime() factory + cache
│   ├── auth.py                # token gate
│   ├── exceptions.py          # {Slug}Error base
│   ├── logging_setup.py       # JSON in prod, human in dev
│   └── services/
│       ├── chat.py            # kaos-agents Runner factory + SessionMemory I/O
│       ├── documents.py       # VFS list/get/delete
│       ├── search.py          # BM25 via kaos-content
│       └── uploads.py         # type/size enforcement + parse routing
├── tests/
│   ├── conftest.py
│   ├── test_smoke.py          # AppTest boots every page
│   ├── test_auth.py
│   ├── test_settings.py
│   └── test_uploads.py        # type/size enforcement
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── docker-compose.postgres.yml
├── README.md
├── CLAUDE.md
└── AGENTS.md
```

## Settings (`{slug}/settings.py`)

All fields documented in `docs/INTEGRATION.md` §3. Streamlit-specific
additions:

- `streamlit_port: int = 8501`
- `streamlit_max_upload_mb: int` — derived from `max_upload_bytes`,
  written into `.streamlit/config.toml` at boot

## Auth (`{slug}/auth.py`)

```python
import hashlib
import hmac

def require(settings: AppSettings) -> None:
    """Block page render if not authenticated."""
    if st.session_state.get("auth_ok"):
        return
    _render_login(settings)
    st.stop()

def _render_login(settings: AppSettings) -> None:
    st.title("Sign in")
    token = st.text_input("Token", type="password")
    if st.button("Sign in"):
        expected = settings.auth_token.get_secret_value()
        if hmac.compare_digest(token, expected):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Invalid token. Check APP_AUTH_TOKEN in .env.")
```

The login page is rendered as part of the page body — Streamlit
doesn't have a separate "before page renders" hook, so every page
calls `require(settings)` as the first line after imports.

## Pages

### `app.py` (entry + sidebar nav)

- Reads `AppSettings()` once, caches in `st.session_state.settings`
- Builds `KaosRuntime` once, caches in `st.session_state.runtime` —
  `@st.cache_resource` so the runtime survives page switches
- Sidebar shows project name, login state, logout button
- Main body: a "what is this" landing card and quick links

### `pages/1_💬_Chat.py`

- `kaos-agents` `Runner` with the `Chat` pattern
- `SessionMemory` persisted to `.kaos-vfs/sessions/{token_hash}/`
- Streamed responses via `st.write_stream` reading from the
  `kaos_agents.wire.events_to_jsonl` async generator
- Tool calls displayed inline using `st.expander` per call
- Token usage + cost tally rendered at the bottom from
  `kaos-llm-client`'s usage tracking

### `pages/2_📤_Upload.py`

- `st.file_uploader` with `type=` matching
  `settings.allowed_upload_types`
- Size enforced server-side (`settings.max_upload_bytes`); Streamlit's
  client-side cap is set to match in `.streamlit/config.toml`
- Routes to `services.uploads.handle()` which:
  1. Validates content-type against allowlist
  2. Sluggifies filename, generates UUID
  3. Calls `kaos-pdf` or `kaos-office` to produce a `ContentDocument`
  4. Stores under `vfs://documents/{uuid}/`
- Renders post-upload preview using `kaos_content.serializers.markdown`

### `pages/3_🔍_Search.py`

- Query input + filter dropdowns (file type, date range)
- Calls `services.search.query()` which uses
  `kaos_content.search.search_document` (BM25, `[nlp]` extra) across
  every document in VFS
- Result cards: title, snippet, score; click-through to Browse

### `pages/4_📚_Browse.py`

- Sidebar: VFS document list with metadata (filename, type, upload
  date, size)
- Main pane: document viewer using `kaos-content` markdown serializer
  + `DocumentView` for outline navigation
- Buttons: "Open in chat" (drops a context handle into
  `st.session_state.chat_context` and switches pages), "Delete"

### `pages/5_⚙_Settings.py`

- Read-only display of `settings.model_dump_redacted()`
- Resolved-from-where column: env / .env / default
- Health summary: VFS path writable? LLM API reachable? Disk space?
- "Run kaos-ui doctor" button → shells out to `kaos-ui doctor .` and
  shows findings inline

## Runtime factory (`{slug}/runtime.py`)

```python
from functools import lru_cache
from kaos_core import KaosRuntime, register_core_tools

@lru_cache(maxsize=1)
def build_runtime() -> KaosRuntime:
    runtime = KaosRuntime()
    register_core_tools(runtime)

    # Optional extras — only register if installed.
    with contextlib.suppress(ImportError):
        from kaos_pdf import register_pdf_tools
        register_pdf_tools(runtime)
    with contextlib.suppress(ImportError):
        from kaos_office import register_office_tools
        register_office_tools(runtime)
    with contextlib.suppress(ImportError):
        from kaos_content.tools import register_content_tools
        register_content_tools(runtime)

    return runtime
```

Optional-suppress is intentional: the vibe coder may strip extras from
`pyproject.toml` for a lighter install. The app keeps working with
fewer tools rather than crashing.

## Services

### `services/chat.py`

- `build_runner(settings, runtime)` returns a `kaos_agents.Runner`
  configured with the user's LLM provider/model from settings
- `load_session(token_hash)` / `save_session(...)` thin VFS wrappers
- Stream wrapper that converts `Runner` events into Streamlit-friendly
  chunks

### `services/documents.py`

CRUD over VFS at `documents/{uuid}/`. Returns typed
`@dataclass(frozen=True, slots=True)` records, never bare dicts.

### `services/search.py`

```python
def query(runtime: KaosRuntime, q: str, *, limit: int = 20) -> list[Hit]:
    """BM25 across every document in VFS. Returns scored hits."""
    # uses kaos_content.search.search_document
```

### `services/uploads.py`

```python
def handle(runtime, settings, file: UploadedFile) -> Document:
    _validate_size(file, settings.max_upload_bytes)
    _validate_type(file, settings.allowed_upload_types)
    return _parse_and_store(runtime, file)
```

Errors raise `{Slug}UploadError` with the agent-friendly shape.

## Makefile

```make
.PHONY: install dev test up down doctor build typecheck lint format

install:
	uv sync
	uv run pre-commit install

dev:
	uv run streamlit run app.py

test:
	uv run pytest tests/ -v

up:
	docker compose up -d --build

down:
	docker compose down

doctor:
	uv run kaos-ui doctor .

build:
	docker compose build

typecheck:
	uv run ty check {slug}/ tests/

lint:
	uv run ruff check {slug}/ pages/ app.py tests/

format:
	uv run ruff format {slug}/ pages/ app.py tests/
```

## Dockerfile

Multi-stage:

1. **Builder**: `python:3.14-slim` → install `uv`, copy
   `pyproject.toml` + `uv.lock`, `uv sync --frozen --no-dev`.
2. **Runtime**: `python:3.14-slim` → non-root `appuser` (uid 1000),
   copy venv from builder, copy app code, expose 8501, healthcheck on
   `/_stcore/health`, `CMD streamlit run app.py --server.address
   0.0.0.0 --server.port 8501 --server.headless true`.

Build args version-pin Python and base image. No secrets baked.

## docker-compose.yml

```yaml
services:
  app:
    build: .
    env_file: .env
    ports:
      - "127.0.0.1:8501:8501"  # localhost-only; public requires explicit override
    volumes:
      - ./.kaos-vfs:/app/.kaos-vfs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501/_stcore/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## docker-compose.postgres.yml (overlay)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      POSTGRES_DB: app
    volumes:
      - pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
  app:
    environment:
      APP_DATABASE_URL: postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@postgres:5432/app
    depends_on:
      postgres:
        condition: service_healthy
volumes:
  pg-data:
```

## Tests

### `tests/test_smoke.py`

```python
from streamlit.testing.v1 import AppTest

def test_app_boots(monkeypatch):
    monkeypatch.setenv("APP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("APP_ENV", "test")
    at = AppTest.from_file("app.py", default_timeout=10).run()
    assert not at.exception

def test_every_page_renders(monkeypatch):
    monkeypatch.setenv("APP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("APP_ENV", "test")
    for page in ("pages/1_💬_Chat.py", "pages/2_📤_Upload.py",
                 "pages/3_🔍_Search.py", "pages/4_📚_Browse.py",
                 "pages/5_⚙_Settings.py"):
        at = AppTest.from_file(page, default_timeout=10).run()
        assert not at.exception, f"{page} raised: {at.exception}"
```

### `tests/test_auth.py`

- Login with correct token → succeeds
- Login with wrong token → fails, shows error
- Pages without auth → blocked

### `tests/test_uploads.py`

- Reject oversize file
- Reject disallowed extension
- Accept allowed file → produces ContentDocument in VFS

### `tests/test_settings.py`

- Refuses to start without `APP_AUTH_TOKEN` in non-test env
- `model_dump_redacted` redacts the token

## Pre-commit

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks: [{id: ruff}, {id: ruff-format}]
  - repo: https://github.com/gitleaks/gitleaks
    hooks: [{id: gitleaks}]
  - repo: local
    hooks:
      - id: ty
        name: ty check
        language: system
        entry: uv run ty check
        types: [python]
        pass_filenames: false
```

## kaos-ui doctor extensions for this kind

When `kaos-ui doctor` runs in a Streamlit scaffold, additional checks:

| Check | Severity | How to fix |
|---|---|---|
| `APP_AUTH_TOKEN` set in `.env` | error | Set it to a long random string |
| `.streamlit/config.toml` has `runOnSave=false` | warning | Set to false for production safety |
| VFS path writable | error | Confirm `./.kaos-vfs/` exists or override `APP_VFS_PATH` |
| Streamlit reachable on configured port | info | Only checked when `make up` is running |

## kaos-ui repo integration test

`kaos-ui/tests/integration/test_scaffold_streamlit.py`:

```python
@pytest.mark.integration
@pytest.mark.slow
def test_scaffold_install_smoke(tmp_path):
    # 1. scaffold
    subprocess.check_call([
        "kaos-ui", "new", "dashboard", "demo",
        "--target", str(tmp_path / "demo"),
    ])
    project = tmp_path / "demo"
    # 2. write a test .env
    (project / ".env").write_text(
        "APP_AUTH_TOKEN=test-token-do-not-use-in-prod\nAPP_ENV=test\n"
    )
    # 3. uv sync
    subprocess.check_call(["uv", "sync"], cwd=project)
    # 4. pytest the scaffolded smoke test
    subprocess.check_call(["uv", "run", "pytest", "tests/test_smoke.py"], cwd=project)
```

## Versions pinned in `pyproject.toml.tmpl`

| Dep | Pin | Why |
|---|---|---|
| python | `>=3.14,<3.15` | KAOS platform default |
| streamlit | `>=1.40,<2.0` | 1.40 is current GA in 2026; major-version pin |
| kaos-core | `>=0.1.0` | platform |
| kaos-content[markdown,nlp] | `>=0.1.0` | document AST + markdown + BM25 |
| kaos-agents | `>=0.1.0` | runner + memory |
| kaos-llm-client | `>=0.1.0` | provider transport |
| kaos-pdf | `>=0.1.0` | upload parsing |
| kaos-office | `>=0.1.0` | upload parsing |
| pydantic | `>=2.11,<3` | settings |
| pydantic-settings | `>=2.8,<3` | settings |
| sqlalchemy | `>=2.0,<3` | optional, for non-trivial state |
| alembic | `>=1.13,<2` | migrations (optional, lazy import) |
