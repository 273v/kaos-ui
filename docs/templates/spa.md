# Template Spec: `web:spa` (fullstack)

> Vite + React SPA frontend + FastAPI on kaos-core backend, wired
> together with TanStack Query and a typed API client. Caddy reverse
> proxy with autocert in compose. SQLite default, Postgres overlay.

## What the vibe coder gets

```bash
kaos-ui new web:spa my-app
cd my-app
make install         # uv sync && pnpm install
make doctor
make up              # docker compose up — Caddy on :443 (autocert) → SPA + API
# or
make dev             # parallel: vite dev :5173 + uvicorn :8000
```

Login page → bearer token from `.env` → SPA can call `/v1/*`. The
backend exposes the standard KAOS surface (chat, documents, search,
upload). The frontend renders it.

The frontend workspace pins `pnpm@11.1.0` and ships hardened pnpm
settings: 72-hour dependency release cooldown, exotic transitive
dependency blocking, strict dependency build scripts, a reviewed
`allowBuilds` list, and exact-version saves. The template does not ship
a static `pnpm-lock.yaml` because package names are templated; the first
`pnpm install` creates the project-specific lockfile, and `kaos-ui
doctor` warns until it is committed.

## Scaffolded layout

```
my-app/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .editorconfig
├── pnpm-workspace.yaml
├── package.json                      # workspace root; runs both apps
├── docker-compose.yml
├── docker-compose.postgres.yml
├── Caddyfile                         # reverse proxy + autocert
├── Makefile
├── README.md
├── CLAUDE.md
├── AGENTS.md
├── backend/
│   ├── pyproject.toml.tmpl
│   ├── .python-version
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 0001_init.py
│   ├── app/
│   │   ├── __init__.py.tmpl
│   │   ├── main.py.tmpl              # FastAPI app + middleware + lifespan
│   │   ├── settings.py               # AppSettings(ModuleSettings)
│   │   ├── runtime.py                # build_runtime() — KaosRuntime factory
│   │   ├── auth.py                   # bearer middleware + login endpoint
│   │   ├── exceptions.py             # {Slug}APIError → KaosCoreError
│   │   ├── deps.py                   # FastAPI dependencies (settings, runtime, current_user)
│   │   ├── logging_setup.py
│   │   ├── routers/
│   │   │   ├── __init__.py.tmpl
│   │   │   ├── auth.py               # POST /v1/auth/login, /logout
│   │   │   ├── health.py.tmpl        # GET /v1/health, /v1/ready
│   │   │   ├── sessions.py           # POST /v1/sessions/{id}/messages (SSE)
│   │   │   ├── documents.py          # GET/DELETE /v1/documents
│   │   │   ├── search.py             # GET /v1/search
│   │   │   └── uploads.py            # POST /v1/uploads (multipart)
│   │   └── services/
│   │       ├── chat.py               # kaos-agents Runner factory
│   │       ├── documents.py          # VFS list/get/delete
│   │       ├── search.py             # BM25 via kaos-content
│   │       └── uploads.py            # type/size enforcement + parse routing
│   └── tests/
│       ├── conftest.py
│       ├── test_health.py
│       ├── test_auth.py
│       ├── test_uploads.py
│       ├── test_search.py
│       └── test_sessions.py          # SSE stream smoke
├── apps/
│   └── spa/
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts
│       ├── tailwind.config.ts
│       ├── postcss.config.js
│       ├── index.html
│       ├── Dockerfile
│       ├── biome.json                # or eslint.config.js — see Phase 1 decision
│       ├── src/
│       │   ├── main.tsx
│       │   ├── env.ts                # parsed VITE_* env vars
│       │   ├── api/
│       │   │   ├── client.ts         # generated from OpenAPI spec
│       │   │   └── query.ts          # TanStack Query hooks
│       │   ├── auth/
│       │   │   ├── context.tsx
│       │   │   └── login-page.tsx
│       │   ├── routes/
│       │   │   ├── __root.tsx
│       │   │   ├── index.tsx
│       │   │   ├── login.tsx
│       │   │   ├── chat.tsx
│       │   │   ├── search.tsx
│       │   │   ├── documents/
│       │   │   │   ├── index.tsx
│       │   │   │   └── $documentId.tsx
│       │   │   ├── upload.tsx
│       │   │   └── settings.tsx
│       │   ├── components/           # shadcn primitives + app components
│       │   ├── lib/
│       │   │   ├── utils.ts
│       │   │   └── streaming.ts      # SSE consumer wired to TanStack Query
│       │   └── styles/
│       │       └── globals.css       # tailwind imports + theme tokens
│       └── tests/
│           ├── setup.ts
│           ├── pages.test.tsx        # vitest + RTL — every route renders
│           └── streaming.test.ts
└── packages/
    └── ui/                           # shared types + shadcn-style primitives
        ├── package.json
        ├── tsconfig.json
        ├── components.json
        └── src/
            ├── components/
            ├── hooks/
            ├── lib/
            └── types/                # zod schemas mirroring backend
```

## Backend: FastAPI on kaos-core

### `app/main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.settings import AppSettings
from app.runtime import build_runtime
from app.routers import auth, documents, health, search, sessions, uploads
from app.auth import bearer_middleware

@asynccontextmanager
async def lifespan(app):
    settings = AppSettings()
    app.state.settings = settings
    app.state.runtime = build_runtime(settings)
    yield

def create_app() -> FastAPI:
    settings = AppSettings()
    app = FastAPI(
        title="{slug}",
        lifespan=lifespan,
        docs_url="/v1/docs" if settings.env != "production" else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(bearer_middleware)
    app.include_router(health.router, prefix="/v1")
    app.include_router(auth.router, prefix="/v1/auth")
    app.include_router(sessions.router, prefix="/v1/sessions")
    app.include_router(documents.router, prefix="/v1/documents")
    app.include_router(search.router, prefix="/v1/search")
    app.include_router(uploads.router, prefix="/v1/uploads")
    return app

app = create_app()
```

### Routes

| Route | Auth | What |
|---|---|---|
| `GET /v1/health` | none | `{"status": "ok"}` |
| `GET /v1/ready` | none | DB + VFS reachable |
| `POST /v1/auth/login` | none | Body: `{token}`. Sets `httpOnly` `Secure` cookie |
| `POST /v1/auth/logout` | none | Clears cookie |
| `GET /v1/auth/me` | bearer | Current session info |
| `POST /v1/sessions/{id}/messages` | bearer | Body: `{message}`. SSE stream of agent events via `kaos_agents.wire.events_to_sse` |
| `GET /v1/sessions/{id}` | bearer | Memory snapshot |
| `GET /v1/documents` | bearer | List, paginated |
| `GET /v1/documents/{id}` | bearer | Full ContentDocument (chunked >256 KB per `mcp-data-flow.md`) |
| `DELETE /v1/documents/{id}` | bearer | Soft delete |
| `GET /v1/search?q=...` | bearer | BM25 |
| `POST /v1/uploads` | bearer | Multipart, type/size enforced |

### `app/auth.py`

```python
import hmac, secrets
from fastapi import Request, Response
from fastapi.responses import JSONResponse

COOKIE_NAME = "{slug}_session"
PUBLIC_PATHS = {"/v1/health", "/v1/ready", "/v1/auth/login", "/v1/docs", "/v1/openapi.json"}

async def bearer_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    settings = request.app.state.settings
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie or not hmac.compare_digest(
        cookie, settings.auth_token.get_secret_value()
    ):
        return JSONResponse(
            {"what": "Not authenticated",
             "how_to_fix": "POST /v1/auth/login with {\"token\": \"<APP_AUTH_TOKEN>\"}",
             "alternative_tool": None},
            status_code=401,
        )
    return await call_next(request)
```

Cookie attributes: `HttpOnly`, `SameSite=Lax`, `Secure` when
`env != "development"`. Bearer-from-cookie pattern is immune to CSRF
under SameSite=Lax with the `lax` enforcement on cross-origin POST.

### Settings additions over the cross-cutting contract

```python
cors_origins: tuple[str, ...] = ("http://localhost:5173",)  # vite dev
backend_port: int = 8000
frontend_port: int = 5173
public_origin: str = "http://localhost:8443"  # caddy front-door, dev autocert
database_url: str = "sqlite+aiosqlite:///./.kaos-vfs/app.db"
```

Production deployments override `cors_origins` and `public_origin` via
env. The validator refuses to load if `env=="production"` and
`cors_origins` includes a wildcard.

### Lifespan + DI

`build_runtime(settings)` returns a singleton `KaosRuntime`. Per-request
DI uses FastAPI dependencies that pull from `app.state`:

```python
def get_runtime(request: Request) -> KaosRuntime:
    return request.app.state.runtime

def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings
```

Per-request `KaosContext` is constructed in middleware and stashed at
`request.state.kaos_context` so logging gets `session_id` + `trace_id`
automatically.

## Frontend

### Stack

- Vite 6 + React 19 + TypeScript 5.6
- TanStack Router (file-based, type-safe)
- TanStack Query (data fetching)
- Tailwind CSS v4 + shadcn/ui (copy-into-repo primitives)
- Zod for schemas
- Biome for lint + format (decision: Biome over Eslint+Prettier — see
  Phase 1 decisions in `PLAN.md`)

### API client

The backend's OpenAPI spec is consumed at build time by
`openapi-typescript` to produce `apps/spa/src/api/client.ts` —
end-to-end typed. Hooks in `api/query.ts` wrap each operation in a
TanStack Query `useQuery` / `useMutation`:

```ts
export function useDocuments() {
  return useQuery({
    queryKey: ['documents'],
    queryFn: () => api.GET('/v1/documents'),
  });
}
```

### Streaming

`POST /v1/sessions/{id}/messages` returns SSE. Frontend consumes via a
small `lib/streaming.ts` helper that wraps `EventSource` (or `fetch`
with `ReadableStream` for SSE-with-headers). The chat page uses it as a
TanStack Query infinite query so retries and cancellation are free.

### Auth flow

1. Frontend posts token to `/v1/auth/login`. Backend sets `httpOnly`
   cookie. Frontend doesn't see the token after that — it's never in
   `localStorage` or JS-readable.
2. All subsequent fetches go with `credentials: "include"`. The cookie
   travels automatically.
3. Logout: `/v1/auth/logout` clears the cookie.

### Routes

| Route | What |
|---|---|
| `/login` | token form |
| `/` | landing — last 5 documents + chat shortcut |
| `/chat` | streaming agent loop |
| `/documents` | list + filter |
| `/documents/$documentId` | viewer |
| `/upload` | drag-drop + progress |
| `/search` | query + results |
| `/settings` | resolved settings (redacted) |

## Compose + Caddy

`docker-compose.yml` brings up: backend, vite-dev-server, caddy. Caddy
proxies `/v1/*` to backend:8000, everything else to vite:5173.
Autocert in production via `tls internal` on dev, real Let's Encrypt
on prod via the `Caddyfile.prod` overlay.

`docker-compose.postgres.yml` overlay adds Postgres and rewrites
`APP_DATABASE_URL`.

## Makefile

```make
	.PHONY: install install-ci verify-deps dev test up down doctor build typecheck lint format db:revision

	install:
		uv sync --directory backend
		pnpm install
		cd backend && uv run pre-commit install

	install-ci:
		pnpm install --frozen-lockfile

	verify-deps:
		pnpm audit signatures

dev:
	# Run both in parallel; trap Ctrl+C
	@trap 'kill 0' INT; \
	cd backend && uv run uvicorn app.main:app --reload --port 8000 & \
	pnpm --filter spa dev & \
	wait

test:
	cd backend && uv run pytest tests/ -v
	pnpm --filter spa test

up:
	docker compose up -d --build

down:
	docker compose down

doctor:
	uv run kaos-ui doctor .

build:
	docker compose build

typecheck:
	cd backend && uv run ty check app/ tests/
	pnpm --filter spa typecheck

lint:
	cd backend && uv run ruff check app/ tests/
	pnpm --filter spa lint

format:
	cd backend && uv run ruff format app/ tests/
	pnpm --filter spa format

db:revision:
	cd backend && uv run alembic revision --autogenerate -m "$(MSG)"
```

## Tests

### Backend

- `test_health.py` — smoke
- `test_auth.py` — login flow + cookie behavior + middleware blocks unauth
- `test_uploads.py` — type/size enforcement + ContentDocument produced
- `test_search.py` — BM25 returns ranked results
- `test_sessions.py` — SSE stream parses; agent events flow through

### Frontend (vitest + RTL)

- `pages.test.tsx` — every route renders without throwing
- `streaming.test.ts` — SSE consumer handles partial events, reconnect
- Playwright e2e (Phase 3) — login → upload → search → chat happy path

### kaos-ui repo integration test

```python
@pytest.mark.integration
@pytest.mark.slow
def test_scaffold_install_build(tmp_path):
    subprocess.check_call(["kaos-ui", "new", "web:spa", "demo",
                           "--target", str(tmp_path / "demo")])
    project = tmp_path / "demo"
    (project / ".env").write_text(
        "APP_AUTH_TOKEN=test-token\nAPP_ENV=test\n"
    )
    subprocess.check_call(["uv", "sync"], cwd=project / "backend")
    subprocess.check_call(["pnpm", "install"], cwd=project)
    subprocess.check_call(
        ["uv", "run", "pytest", "tests/test_health.py"],
        cwd=project / "backend",
    )
    subprocess.check_call(
        ["pnpm", "--filter", "spa", "build"],
        cwd=project,
    )
```

## kaos-ui doctor extensions for this kind

| Check | Severity | How to fix |
|---|---|---|
| `APP_AUTH_TOKEN` set in `.env` | error | Set it; `head -c 32 /dev/urandom \| base64` is a fine source |
| `APP_CORS_ORIGINS` not `*` in production | error | Set explicit list in `.env` |
| `packageManager` pins pnpm 11.1+ | error | Restore the root package.json pin |
| Hardened `pnpm-workspace.yaml` settings present | error | Restore cooldown, strict build-script, exotic-subdep, and exact-save settings |
| `pnpm-lock.yaml` committed after first install | warning | Run `pnpm install`, review dependency prompts, commit lockfile |
| `pnpm` available and 11.1+ | warning | Run `kaos setup env` |
| Caddy port 443 free (when `make up` running) | warning | Pick a different `APP_PUBLIC_PORT` |
| Frontend OpenAPI client up to date with backend | warning | Run `pnpm --filter spa codegen` |

## Pinned versions

### Backend

| Dep | Pin |
|---|---|
| python | `>=3.14,<3.15` |
| fastapi | `>=0.115,<1.0` |
| uvicorn[standard] | `>=0.32,<1.0` |
| sqlalchemy | `>=2.0,<3` |
| alembic | `>=1.13,<2` |
| kaos-core | `>=0.1.0` |
| kaos-agents | `>=0.1.0` |
| kaos-content | `>=0.1.0` |
| kaos-llm-client | `>=0.1.0` |
| kaos-pdf | `>=0.1.0` |
| kaos-office | `>=0.1.0` |

### Frontend

| Dep | Pin |
|---|---|
| react | `19.x` |
| react-dom | `19.x` |
| @tanstack/react-router | `1.x` |
| @tanstack/react-query | `5.x` |
| tailwindcss | `4.x` |
| zod | `3.x` |
| vite | `6.x` |
| typescript | `5.6.x` |
| biome | `1.9.x` |
| openapi-typescript | `7.x` |
