.PHONY: install dev test up down doctor build typecheck lint format clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies + pre-commit hooks
	uv sync
	uv run pre-commit install

dev:  ## Run the Streamlit app locally
	uv run streamlit run app.py

test:  ## Run the test suite
	uv run pytest tests/ -v

up:  ## Build and start via docker compose (localhost only)
	docker compose up -d --build

down:  ## Stop docker compose
	docker compose down

doctor:  ## Health-check the project
	uv run kaos-ui doctor .

build:  ## Build the Docker image
	docker compose build

typecheck:  ## ty static type check
	uv run ty check {{KAOS_PYTHON_MODULE}}/ tests/

lint:  ## Lint Python sources
	uv run ruff check {{KAOS_PYTHON_MODULE}}/ pages/ app.py tests/

format:  ## Auto-format Python sources
	uv run ruff format {{KAOS_PYTHON_MODULE}}/ pages/ app.py tests/

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .ty_cache .coverage htmlcov dist
	find . -type d -name __pycache__ -exec rm -rf {} +
