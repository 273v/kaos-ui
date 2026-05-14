.PHONY: install dev test doctor build typecheck lint format console clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies + pre-commit hooks
	uv sync
	uv run pre-commit install

dev:  ## Run the TUI
	uv run python -m {{KAOS_PYTHON_MODULE}}

console:  ## Run textual-dev console (separate terminal) for live debug
	uv run textual console

test:  ## Run the test suite
	uv run pytest tests/ -v

doctor:  ## Health-check the project
	uv run kaos-ui doctor .

build:  ## Build wheel + sdist for distribution (e.g., `pipx install dist/...whl`)
	uv build

typecheck:  ## ty static type check
	uv run ty check {{KAOS_PYTHON_MODULE}}/ tests/

lint:  ## Lint Python sources
	uv run ruff check {{KAOS_PYTHON_MODULE}}/ tests/

format:  ## Auto-format Python sources
	uv run ruff format {{KAOS_PYTHON_MODULE}}/ tests/

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .ty_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
