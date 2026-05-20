# Template Spec: `tui:textual`

> A keyboard-driven terminal app with kaos-agents wired in by default.
> Three screens, async, persisted session memory, no auth (single-user
> terminal app).

## What the vibe coder gets

```bash
kaos-ui new tui my-tool
cd my-tool
make install
make dev             # full-screen TUI in their terminal
```

Three screens, navigated by keyboard:

- **Chat** (default) — talks to the user's preferred LLM via
  `kaos-agents` Runner, with all installed KAOS tools available
- **Documents** — browse files in `~/.kaos/{slug}/vfs/`
- **Settings** — resolved settings (redacted), keyboard shortcuts ref

## Scaffolded layout

```
my-tool/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version
├── pyproject.toml
├── {slug}/
│   ├── __init__.py
│   ├── __main__.py            # `python -m {slug}` → app.run()
│   ├── app.py                 # the Textual App; key bindings; screen routing
│   ├── settings.py            # AppSettings(ModuleSettings)
│   ├── runtime.py             # build_runtime() factory
│   ├── exceptions.py
│   ├── styles.tcss            # Textual CSS for theming
│   └── screens/
│       ├── chat.py
│       ├── documents.py
│       └── settings.py
├── tests/
│   ├── conftest.py
│   ├── test_smoke.py          # boot in headless mode + assert title
│   └── test_settings.py
├── Makefile
├── Dockerfile                 # optional; TUIs are usually pip-installed
├── README.md
├── CLAUDE.md
└── AGENTS.md
```

## Settings

Inherits the contract from `docs/INTEGRATION.md` §3. TUI-specific
fields:

```python
class AppSettings(ModuleSettings):
    env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Single-user TUI — VFS lives under XDG-friendly path by default.
    vfs_path: Path = Path.home() / ".kaos" / "{slug}" / "vfs"

    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-4-7"

    # No auth_token — TUIs are single-user.

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")
```

The `.env` file is still required for LLM provider keys
(`ANTHROPIC_API_KEY` etc.), so the refuse-to-start-without-env rule
still applies.

## Screens

### `screens/chat.py` — default

- Top: scrollable transcript using Textual's `RichLog` widget
- Bottom: `Input` widget, Enter to submit
- Async tasks dispatch user messages through `kaos-agents` Runner
- Streaming: each chunk appended to the transcript via `app.call_from_thread`
- Tool calls collapsed by default; press `Tab` to expand
- Keyboard:
  - `Ctrl+L` — clear transcript (memory preserved)
  - `Ctrl+N` — new session (memory cleared)
  - `Ctrl+S` — save transcript to `~/.kaos/{slug}/transcripts/`
  - `Ctrl+D` — focus documents screen

### `screens/documents.py`

- Left: `DirectoryTree` widget rooted at VFS path
- Right: document viewer using `kaos-content` markdown serializer +
  `DocumentView` for outline
- Keyboard:
  - `Enter` — open
  - `c` — open in chat (passes handle as context)
  - `Delete` — soft-delete (moves to trash subdir)

### `screens/settings.py`

- Static read-only screen. `DataTable` showing field / value / source-tier
- Token-shaped values rendered redacted via `model_dump_redacted`
- "Run doctor" button → spawns `kaos-ui doctor .` in a subshell, shows
  findings in a `ScrollView`
- Footer: keyboard shortcuts reference

## App entry (`{slug}/app.py`)

```python
from textual.app import App
from textual.binding import Binding

from {slug}.screens.chat import ChatScreen
from {slug}.screens.documents import DocumentsScreen
from {slug}.screens.settings import SettingsScreen
from {slug}.settings import AppSettings
from {slug}.runtime import build_runtime

class {Slug}App(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        Binding("ctrl+1", "switch('chat')", "Chat"),
        Binding("ctrl+2", "switch('documents')", "Documents"),
        Binding("ctrl+3", "switch('settings')", "Settings"),
        Binding("ctrl+q", "quit", "Quit"),
    ]
    SCREENS = {
        "chat": ChatScreen,
        "documents": DocumentsScreen,
        "settings": SettingsScreen,
    }

    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings()
        self.runtime = build_runtime(self.settings)

    def on_mount(self) -> None:
        self.push_screen("chat")

    def action_switch(self, name: str) -> None:
        self.switch_screen(name)
```

## Runtime factory

Same shape as Streamlit's — `lru_cache(maxsize=1)`, registers
`kaos-core` tools and any installed extras with `contextlib.suppress`.

## Logging in a TUI

Textual owns stdout/stderr while the app runs, so logs from
`kaos.app.{slug}` need to route somewhere visible. Default: write to
`~/.kaos/{slug}/log.jsonl` (always JSON in TUI mode, regardless of
`ENV`). The Settings screen has a "tail log" button.

## Makefile

```make
.PHONY: install dev test doctor build typecheck

install:
	uv sync
	uv run pre-commit install

dev:
	uv run python -m {slug}

test:
	uv run pytest tests/ -v

doctor:
	uv run kaos-ui doctor .

build:
	uv build  # produces wheel + sdist for `pipx install` distribution

typecheck:
	uv run ty check {slug}/ tests/
```

No `up`/`down` — TUIs aren't compose'd. Dockerfile exists but is
optional (some teams ship TUIs as pip-installable wheels rather than
containers).

## Tests

### `tests/test_smoke.py`

```python
import pytest
from {slug}.app import {Slug}App

@pytest.mark.asyncio
async def test_app_boots(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    app = {Slug}App()
    async with app.run_test() as pilot:
        assert app.title  # at least a title rendered
        await pilot.press("ctrl+2")  # switch to documents
        assert app.screen.id in ("documents", "Documents")
        await pilot.press("ctrl+3")  # switch to settings
        assert app.screen.id in ("settings", "Settings")
```

Uses Textual's built-in `App.run_test()` async context manager.

## Pre-commit

Same as Streamlit (ruff + ruff-format + ty + gitleaks). No `eslint`
since there's no JS.

## kaos-ui doctor extensions for this kind

| Check | Severity | How to fix |
|---|---|---|
| At least one LLM provider key in `.env` | error | Set `ANTHROPIC_API_KEY` or equivalent |
| VFS path writable | error | Override `APP_VFS_PATH` to a writable location |
| Terminal supports 256 colors | warning | Some Textual styling will render plainly |

## kaos-ui repo integration test

```python
@pytest.mark.integration
@pytest.mark.slow
def test_scaffold_install_smoke(tmp_path):
    subprocess.check_call(["kaos-ui", "new", "tui", "demo",
                           "--target", str(tmp_path / "demo")])
    project = tmp_path / "demo"
    (project / ".env").write_text("APP_ENV=test\nANTHROPIC_API_KEY=test\n")
    subprocess.check_call(["uv", "sync"], cwd=project)
    subprocess.check_call(["uv", "run", "pytest", "tests/test_smoke.py"], cwd=project)
```

## Pinned versions

| Dep | Pin | Why |
|---|---|---|
| python | `>=3.14,<3.15` | platform |
| textual | `>=0.85,<1.0` | major-version pin |
| kaos-core | `>=0.1.0` | platform |
| kaos-agents | `>=0.1.0` | runner |
| kaos-content[markdown] | `>=0.1.0` | document viewer |
| kaos-llm-client | `>=0.1.0` | provider transport |
