.PHONY: install install-ci verify-deps sync-ui dev test up down doctor build typecheck lint format codegen clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

sync-ui:  ## Stamp packages/ui from the kaos-ui web:spa template
	./scripts/sync-ui.sh

install: sync-ui  ## Sync packages/ui, then install backend (uv) + frontend (pnpm) deps
	cd backend && uv sync
	pnpm install

install-ci:  ## CI install (assumes packages/ui already synced + frozen lockfiles)
	./scripts/sync-ui.sh
	cd backend && uv sync --frozen
	pnpm install --frozen-lockfile

verify-deps:  ## Verify npm package signatures/provenance where available
	pnpm audit signatures

dev:  ## Run backend (uvicorn) + frontend (vite) in parallel
	@trap 'kill 0' INT; \
	cd backend && uv run uvicorn app.main:app --reload --port 8000 & \
	pnpm --filter "*spa" dev & \
	wait

test:  ## Run backend pytest + frontend vitest
	cd backend && uv run pytest tests/ -v
	pnpm test

up:  ## Build and start docker compose stack (caddy + backend, localhost only)
	docker compose up -d --build

down:  ## Stop docker compose
	docker compose down

doctor:  ## Health-check the project — verifies sync-ui clean + imports work
	@echo "→ checking sync-ui is up-to-date..."
	./scripts/sync-ui.sh > /dev/null
	@echo "→ checking backend imports..."
	cd backend && uv run python -c "from app.main import app; print(f'backend ok: {len(app.routes)} routes')"
	@echo "→ checking frontend typecheck..."
	pnpm typecheck
	@echo "✓ all green"

build:  ## Build container images
	docker compose build

typecheck:  ## ty (backend) + tsc (frontend)
	cd backend && uv run ty check app/ tests/
	pnpm typecheck

lint:  ## Lint everything
	cd backend && uv run ruff check app/ tests/
	pnpm lint

format:  ## Auto-format
	cd backend && uv run ruff format app/ tests/
	pnpm format

codegen:  ## Regenerate the typed API client from the backend's OpenAPI spec
	pnpm --filter "*spa" codegen

clean:
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.ty_cache backend/.coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf apps/spa/dist apps/spa/.vite
	rm -rf packages/ui
