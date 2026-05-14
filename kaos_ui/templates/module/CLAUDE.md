# {{KAOS_PROJECT_NAME}}

KAOS module package with MCP tools, CLI, and serve.

## QA Sequence

```bash
ruff format {{KAOS_PYTHON_MODULE}}/ tests/
ruff check --fix {{KAOS_PYTHON_MODULE}}/ tests/
ty check {{KAOS_PYTHON_MODULE}}/ tests/
pytest tests/ -v
```

## Architecture

- `{{KAOS_PYTHON_MODULE}}/tools.py` — KaosTool definitions with ToolAnnotations
- `{{KAOS_PYTHON_MODULE}}/cli.py` — CLI with `--json` support
- `{{KAOS_PYTHON_MODULE}}/serve.py` — MCP server entry point

## Key Patterns

- All tools must have `ToolAnnotations` (never None)
- Use `readOnlyHint=True` for read-only tools
- Error messages: what went wrong + how to fix + alternative tool
- Flat inputs with `ParameterSchema`, not nested dicts
- Follow naming: `kaos-{{KAOS_PROJECT_SLUG}}-{action}`
