# {{KAOS_PROJECT_NAME}}

FastAPI backend with KAOS integration for document processing.

## QA Sequence

```bash
uv run ruff format app/ tests/
uv run ruff check --fix app/ tests/
uv run ty check app/ tests/
uv run pytest tests/ -v
```

## Architecture

- `app/main.py` — FastAPI application with lifespan and CORS
- `app/config.py` — Pydantic Settings (`KAOS_` env prefix)
- `app/routers/` — API route handlers
- `app/services/` — Business logic wrapping KAOS packages

## Key Patterns

- Use `kaos-pdf` for PDF extraction, `kaos-web` for web content
- All extraction produces `ContentDocument` from `kaos-content`
- Return structured JSON, not raw markdown
- Use async endpoints where possible
