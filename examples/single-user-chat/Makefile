.PHONY: install install-ci verify-deps sync-ui dev dev-bg stop logs test up down doctor build typecheck lint format codegen clean help

# Dev env — overridable by the caller. The token must be ≥32 chars
# (kaos_agents enforces this). Use a placeholder; production deploys
# pass through KAOS_AGENTS_API_API_TOKEN explicitly.
DEV_TOKEN ?= demo-token-must-be-at-least-32-chars-long-for-validation
DEV_ENV ?= development
DEV_DIR ?= .dev
BACKEND_HOST ?= 0.0.0.0
BACKEND_PORT ?= 8000
SPA_HOST ?= 0.0.0.0
SPA_PORT ?= 5173

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

dev:  ## Run backend (uvicorn) + frontend (vite) in parallel — foreground
	@trap 'kill 0' INT; \
	cd backend && env KAOS_AGENTS_API_API_TOKEN="$(DEV_TOKEN)" APP_ENV="$(DEV_ENV)" \
		uv run uvicorn app.main:app --reload --host "$(BACKEND_HOST)" --port "$(BACKEND_PORT)" & \
	pnpm --filter "*spa" exec vite --host "$(SPA_HOST)" --port "$(SPA_PORT)" & \
	wait

dev-bg:  ## Start backend + frontend in background; PIDs in .dev/, logs in .dev/{backend,spa}.log
	@mkdir -p "$(DEV_DIR)"
	@if [ -f "$(DEV_DIR)/backend.pid" ] && kill -0 $$(cat "$(DEV_DIR)/backend.pid") 2>/dev/null; then \
		echo "backend already running (pid $$(cat $(DEV_DIR)/backend.pid)); run 'make stop' first"; exit 1; \
	fi
	@if [ -f "$(DEV_DIR)/spa.pid" ] && kill -0 $$(cat "$(DEV_DIR)/spa.pid") 2>/dev/null; then \
		echo "spa already running (pid $$(cat $(DEV_DIR)/spa.pid)); run 'make stop' first"; exit 1; \
	fi
	@(cd backend && nohup env KAOS_AGENTS_API_API_TOKEN="$(DEV_TOKEN)" APP_ENV="$(DEV_ENV)" \
		uv run uvicorn app.main:app --reload --host "$(BACKEND_HOST)" --port "$(BACKEND_PORT)" \
		> "../$(DEV_DIR)/backend.log" 2>&1) & echo $$! > "$(DEV_DIR)/backend.pid"
	@(nohup pnpm --filter "*spa" exec vite --host "$(SPA_HOST)" --port "$(SPA_PORT)" \
		> "$(DEV_DIR)/spa.log" 2>&1) & echo $$! > "$(DEV_DIR)/spa.pid"
	@echo "→ backend: http://localhost:$(BACKEND_PORT) (pid $$(cat $(DEV_DIR)/backend.pid), log: $(DEV_DIR)/backend.log)"
	@echo "→ spa:     http://localhost:$(SPA_PORT) (pid $$(cat $(DEV_DIR)/spa.pid), log: $(DEV_DIR)/spa.log)"
	@echo "→ token:   $(DEV_TOKEN)"
	@echo "Stop with: make stop"

stop:  ## Kill whatever's listening on the dev ports — robust against nohup re-parenting
	@for port in "$(BACKEND_PORT)" "$(SPA_PORT)"; do \
		pids=$$(ss -tlnpH "sport = :$$port" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); \
		if [ -n "$$pids" ]; then \
			for pid in $$pids; do \
				pkill -TERM -P "$$pid" 2>/dev/null || true; \
				kill -TERM "$$pid" 2>/dev/null && echo "killed pid $$pid (port $$port)"; \
			done; \
		fi; \
	done
	@rm -f "$(DEV_DIR)/backend.pid" "$(DEV_DIR)/spa.pid"

logs:  ## Tail both dev-bg logs in parallel
	@if [ ! -f "$(DEV_DIR)/backend.log" ] && [ ! -f "$(DEV_DIR)/spa.log" ]; then \
		echo "no dev logs found; run 'make dev-bg' first"; exit 1; \
	fi
	@tail -F "$(DEV_DIR)/backend.log" "$(DEV_DIR)/spa.log"

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
