# {{KAOS_PROJECT_NAME}}

FastAPI backend with KAOS integration.

## Quickstart

```bash
uv sync
uv run fastapi dev app/main.py
```

Open http://localhost:8000/docs for the interactive API docs.

## Endpoints

- `GET /health` — Health check
- `POST /api/v1/documents/extract` — Upload a file for extraction

## Development

```bash
uv run ruff format app/ tests/
uv run ruff check --fix app/ tests/
uv run pytest tests/ -v
```
