# {{KAOS_PROJECT_NAME}}

KAOS module package.

## Quickstart

```bash
uv sync
uv run kaos-{{KAOS_PROJECT_SLUG}} --help
```

## MCP Server

```bash
uv run python -m {{KAOS_PYTHON_MODULE}} serve
```

## Development

```bash
uv run ruff format {{KAOS_PYTHON_MODULE}}/ tests/
uv run ruff check --fix {{KAOS_PYTHON_MODULE}}/ tests/
uv run ty check {{KAOS_PYTHON_MODULE}}/ tests/
uv run pytest tests/ -v
```
