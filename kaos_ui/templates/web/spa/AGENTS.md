# {{KAOS_PROJECT_NAME}} — Agent Instructions

## Project Structure

This is a full-stack application with a FastAPI backend and a Next.js frontend,
connected via a Caddy reverse proxy.

## Backend

- Framework: FastAPI
- Language: Python 3.14+
- Package manager: uv
- KAOS packages: kaos-core, kaos-content, kaos-pdf, kaos-web
- API prefix: `/api/v1/`

## Frontend

- Framework: Next.js (scaffold in `frontend/` if not yet created)
- API calls go to `/api/v1/*` (proxied by Caddy)

## Conventions

- Backend endpoints return JSON
- Use `--json` flag for CLI commands
- All KAOS extraction produces `ContentDocument` objects
- Environment variables use `KAOS_` prefix
