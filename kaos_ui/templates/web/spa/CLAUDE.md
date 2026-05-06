# {{KAOS_PROJECT_NAME}}

Full-stack application with FastAPI backend and Vite/React SPA.

## Architecture

- `backend/` -- FastAPI app with KAOS packages
- `apps/spa/` -- Vite + React + TanStack Router SPA
- `packages/ui/` -- Shared components, hooks, types, styles (@kaos/ui)
- `Caddyfile` -- Reverse proxy configuration (SSR variant)
- `docker-compose.yml` -- All services

## Backend QA

```bash
cd backend
ruff format app/ tests/
ruff check --fix app/ tests/
pytest tests/ -v
```

## Frontend QA

```bash
pnpm typecheck
pnpm build
```

## Running

```bash
docker compose up                               # All services
cd backend && uv run fastapi dev app/main.py    # Backend only
pnpm dev                                        # Frontend dev server
```
