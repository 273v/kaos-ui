# {{KAOS_PROJECT_NAME}} — Agent Runbook

> Read this BEFORE editing anything. Rules for an LLM agent working
> inside this scaffold.

## What this project is

A Textual TUI scaffolded by `kaos-ui new tui`. It runs on `kaos-core`
runtime + KAOS modules (`kaos-agents` for chat, `kaos-content` for
documents, `kaos-llm-client` for LLM transport). Screens are thin —
business logic lives in `{{KAOS_PYTHON_MODULE}}/services/`.

## Files NEVER edit

- `uv.lock`                                — managed by `uv sync`
- `.venv/`, `__pycache__/`, build artifacts — generated
- `.env`                                   — secrets the user owns
- `.gitignore`                             — adding lines is fine, removing is not
- `pyproject.toml [build-system]` and `[tool.hatch.*]` — packaging metadata

## Files that DO need updating when you add features

| Adding | Goes in | Don't forget |
|---|---|---|
| A new screen | `{{KAOS_PYTHON_MODULE}}/screens/<name>.py` | register in `app.py` `SCREENS` + `BINDINGS` + `tests/test_smoke.py` |
| Business logic | `{{KAOS_PYTHON_MODULE}}/services/<name>.py` | a unit test, lazy-import KAOS deps to keep boot fast |
| A new setting | `{{KAOS_PYTHON_MODULE}}/settings.py` | `.env.example` + redaction if `SecretStr` |
| A new exception | `{{KAOS_PYTHON_MODULE}}/exceptions.py` (subclass `AppError`) | `what / how_to_fix / alternative` shape |
| Styling | `{{KAOS_PYTHON_MODULE}}/styles.tcss` | the new selector targets a real widget tree node |

## How to add a new screen (worked example)

```python
# {{KAOS_PYTHON_MODULE}}/screens/reports.py
"""Reports screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class ReportsScreen(Screen):
    """One-line description shown in tracebacks."""

    BINDINGS = []  # screen-local key bindings (in addition to app-level)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("Reports", classes="title")
            # ... real content here ...
        yield Footer()
```

```python
# {{KAOS_PYTHON_MODULE}}/app.py — register the screen:
from {{KAOS_PYTHON_MODULE}}.screens.reports import ReportsScreen

class App(App):
    SCREENS = {
        # ... existing ...
        "reports": ReportsScreen,
    }
    BINDINGS = [
        # ... existing ...
        Binding("ctrl+4", "switch('reports')", "Reports"),
    ]
```

```python
# tests/test_smoke.py — add to the screen list:
SCREEN_NAMES = ("chat", "documents", "settings", "reports")
```

Run `make test` to confirm the screen mounts and key binding fires.

## How to add streaming work without freezing the UI

Use Textual's `@work` decorator. NEVER `await` an LLM call directly in
an event handler — that blocks the event loop:

```python
from textual import work

class ChatScreen(Screen):
    @work(exclusive=True, group="chat")
    async def submit(self, message: str) -> None:
        runner = chat_service.build_runner(self.app.settings, self.app.runtime)
        async for event in chat_service.stream(runner, message, session_id):
            # call_from_thread is safe from any worker context
            self.app.call_from_thread(self._append_token, event)
```

`exclusive=True` cancels any in-flight worker in the same group, which
is the right behavior when the user hits Enter twice.

## Conventions inside this project

- **Settings**: never read `os.environ` directly; pull from `self.app.settings`.
- **Logging**: use `kaos_core.logging.get_logger("kaos.app.{{KAOS_PROJECT_SLUG}}.<sub>")`
  via the `app_logger("<sub>")` helper. Logs go to a file — never `print()`.
- **Errors**: raise subclasses of `AppError`. Every error has
  `what / how_to_fix / alternative` content.
- **Heavy ops**: `@work` decorator for anything that takes >50ms.
- **Lazy imports**: `kaos-agents`, `kaos-content`, etc. are imported
  inside service function bodies — keeps `app.py` fast to import even
  when extras aren't installed.
- **Secrets**: `SecretStr` for everything; `.get_secret_value()` only at
  the wire boundary. Never log secrets.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `SettingsError: ...` at startup | Read the message — it tells you exactly what to set in `.env` |
| TUI renders garbage / colors wrong | Ensure your terminal supports 256 colors (`echo $TERM`); fall back to `TERM=xterm-256color` |
| Copy-paste from alt-screen mode includes terminal junk | Hold `Shift` while selecting in most terminals (iTerm2, Wezterm, Alacritty); see kaos-ui PATTERNS.md §Textual |
| `KeyError: "Attempt to overwrite 'X' in LogRecord"` | `extra={"X": ...}` collides with a reserved field. Rename. See kaos-ui PATTERNS.md |
| `App.run_test()` hangs in CI | Set `TERM=dumb` and `NO_COLOR=1` in the test environment |
| Worker logs scroll past too fast | Run `make console` in another terminal to capture them |

## Production / distribution checklist

> **Before distributing:** read `kaos-ui/docs/DEPLOYMENT.md` for the
> end-to-end deploy guide. TUIs ship via `pipx install dist/*.whl`
> rather than docker — but the kaos-* PyPI gap still applies.

- [ ] `APP_ENV=production` set in `.env` if shipping a binary
- [ ] `APP_DEBUG=false`
- [ ] LLM API key set for `APP_LLM_PROVIDER`
- [ ] `make build` produces a wheel
- [ ] `pipx install dist/*.whl` then test the binary in a clean shell

## Local dev with kaos-modules workspace

If you scaffolded this inside the `kaos-modules` workspace (kaos-* not
yet on PyPI), append to `pyproject.toml`:

```toml
[tool.uv.sources]
kaos-core      = { path = "../kaos-core",      editable = true }
kaos-agents    = { path = "../kaos-agents",    editable = true }
kaos-content   = { path = "../kaos-content",   editable = true }
kaos-llm-client = { path = "../kaos-llm-client", editable = true }
```

## Required checklists (KAOS top-level)

Apply these from `kaos-modules/docs/python/checklists/`:

- 03-implement, 04-test, 05-quality, 07-commit
