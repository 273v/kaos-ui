# {{KAOS_PROJECT_NAME}}

Full-stack application: FastAPI backend + Vite/React SPA + Caddy reverse proxy.

## Quickstart

```bash
cp .env.example .env
docker compose up
```

Open http://localhost to view the application.

## Development

### Backend

```bash
cd backend
uv sync
uv run fastapi dev app/main.py
```

### Frontend

```bash
pnpm install
pnpm dev
```

The SPA dev server runs on http://localhost:5173 with HMR.

## Architecture

- **Caddy** -- Reverse proxy on port 80/443, routes `/api/*` to backend, serves SPA static files
- **Backend** -- FastAPI with KAOS integration on port 8000
- **SPA** -- Vite + React + TanStack Router (apps/spa)
- **@kaos/ui** -- Shared component and hook library (packages/ui)
