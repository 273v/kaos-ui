# kaos-ui PATTERNS — codified lessons

> Things that bit us. Future agents reading this don't repeat the bugs.
> Add to this file every time the integration test or a code review
> catches something subtle.

## Settings

### Refuse to start with weak production config

Every template's `AppSettings` ships a `model_validator(mode="after")`
that hard-fails the app's startup when:

- Any non-test environment is missing required secrets.
- `APP_ENV=production` AND `APP_DEBUG=true`.
- `APP_ENV=production` AND `APP_AUTH_TOKEN` is a well-known weak literal
  (`changeme`, `password`, `admin`, `dev`, `test`, `default`, `secret`).
- `APP_ENV=production` AND `APP_AUTH_TOKEN` length < 32.

Failures raise `SettingsError` with a `what / how_to_fix / alternative`
message. **Never** silently fall back to a default — vibe coders deploy
what runs.

Source: research synthesis, [pydantic-settings #530](https://github.com/pydantic/pydantic-settings/issues/530).

### Test setting overrides — always pass `_env_file=None`

```python
def test_some_settings_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("APP_AUTH_TOKEN", raising=False)
    with pytest.raises(SettingsError):
        AppSettings(_env_file=None)   # ← required
```

Without `_env_file=None`, pydantic-settings reads the project's `.env`
file from the current working directory, which overrides `monkeypatch`
deletions. The integration test was hiding a real bug behind this for
half an hour before it was found.

### `model_dump_redacted()` walks ALL `SecretStr` fields

```python
def model_dump_redacted(self) -> dict[str, object]:
    data = self.model_dump()
    for name in type(self).model_fields:
        value = getattr(self, name)
        if isinstance(value, SecretStr):
            secret = value.get_secret_value()
            data[name] = "***" if len(secret) <= 8 else f"{secret[:4]}...{secret[-4:]}"
    return data
```

Hardcoding a single field name (e.g. `auth_token`) silently leaks any
SecretStr added later. The walk is one-line cheap and future-proof.

### `env_file` fallback for backends in subdirectories

When a template has the FastAPI backend in a `backend/` subdir
(`web:spa`), uvicorn typically runs as `cd backend && uvicorn ...`.
pydantic-settings looks for `.env` relative to cwd → finds none →
required-secret validator fires.

Fix: `env_file=("../.env", ".env")` — try project root first, then
backend-local. Both `cd backend && uvicorn` and project-root
invocations resolve correctly.

This only matters for templates whose Python lives in a subdir.
Streamlit and Textual put their entrypoints at the project root and
don't need it.

### `Annotated[..., NoDecode]` for tuple env vars

pydantic-settings tries to JSON-parse env var values destined for
tuple/list-typed fields. A vibe coder typing
`APP_CORS_ORIGINS=https://a,https://b` gets `JSONDecodeError`, not
the expected tuple.

```python
from pydantic_settings import NoDecode

cors_origins: Annotated[tuple[str, ...], NoDecode] = (...)

@field_validator("cors_origins", mode="before")
@classmethod
def _split_csv(cls, value: object) -> object:
    if isinstance(value, str):
        return tuple(s.strip() for s in value.split(",") if s.strip())
    return value
```

`NoDecode` opts the field out of the default JSON parser; the
`field_validator(mode="before")` runs after. Comma-separated env
input now works; JSON-array input still works as a fallback.

### Cookie `Secure` flag in test env breaks TestClient

`secure=settings.env != "development"` flagged the cookie `Secure` in
test env too. `TestClient` (and curl in dev) speak http://, so
browsers/test-clients drop `Secure` cookies. Fix:
`secure = env == "production"`. Dev + test both speak http; prod
gets the flag.

## Logging

### LogRecord has reserved attributes — don't collide

Python's `logging` module raises `KeyError: "Attempt to overwrite 'X'
in LogRecord"` when `extra={"X": ...}` collides with a built-in
LogRecord attribute. Reserved keys (do not use as `extra` keys):

```
args, asctime, created, exc_info, exc_text, filename, funcName,
levelname, levelno, lineno, message, module, msecs, msg, name,
pathname, process, processName, relativeCreated, stack_info, thread,
threadName, taskName
```

Common bugs we hit:
- `extra={"name": ...}` in `scaffolder.py` (collided with
  `LogRecord.name` — fixed by renaming to `project_name` /
  `template_kind`).
- `extra={"filename": ...}` in `services/uploads.py` (collided with
  `LogRecord.filename` — fixed by renaming to `original_filename`).

The `_RESERVED_LOGRECORD_KEYS` constant in
`{slug}/logging_setup.py` is the authoritative list; use it when
writing custom JSON formatters.

### CWE-117 log injection — strip CR/LF

Templates ship a `_strip_crlf` helper in their JSON formatter that
replaces `\r` and `\n` in user-controlled string values with literal
`\\r` / `\\n`. Without this, an attacker who controls a logged value
(an upload's filename, a chat message) can forge fake log lines —
classic CWE-117. The cost is one `.replace()` per logged string; keep
it.

### `_HumanFormatter` must clear `record.args`

The naive implementation:

```python
class _HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg = _strip_crlf(record.getMessage())
        return super().format(record)
```

…has a latent bug. `record.getMessage()` substitutes the args (turning
`"X %d", (7,)` into `"X 7"`). We assign that result back to
`record.msg`. Then `super().format(record)` calls `record.getMessage()`
*again* — which retries the `%`-substitution on the now-substituted
string, raising
`TypeError: not all arguments converted during string formatting` for
any caller that used `logger.info("X %d", n)`.

Fix: clear `record.args` after substitution:

```python
record.msg = _strip_crlf(record.getMessage())
record.args = ()
return super().format(record)
```

Templates carry a regression test (`tests/test_logging.py`) that pins
this; future changes to the formatter that re-introduce double-format
will fail in CI.

## Scaffolder

### Class-name placeholders vs module-name placeholders

`{{KAOS_PYTHON_MODULE}}` is the slug-with-underscores form (e.g.
`scaffold_board`). It is **not** PascalCase and is **not** suitable as a
class-name prefix — `{{KAOS_PYTHON_MODULE}}Error` becomes
`scaffold_boardError`, which is ugly but valid Python (so the bug
hides past `ast.parse`).

Convention: every template's exception base is named **`AppError`**
literally, regardless of project name. Subclasses follow standard
PascalCase (`AuthError`, `UploadError`, `SettingsError`). The only
project-name substitution in identifier positions is the package name
itself (`{{KAOS_PYTHON_MODULE}}`).

### `KAOS_NPM_SLUG` for npm package names

`KAOS_PROJECT_SLUG` uses underscores (Python-safe). NPM accepts
hyphens but not underscores in many tooling surfaces (`@my_app/ui`
trips pnpm's package-name validator in some workspace configurations).

Templates that emit npm-shaped names use `KAOS_NPM_SLUG`:

```json
{ "name": "@{{KAOS_NPM_SLUG}}/spa" }
```

For input `"My App"` → `KAOS_PROJECT_SLUG = "my_app"` (Python),
`KAOS_NPM_SLUG = "my-app"` (npm). For `"my-app"` already-hyphenated
input both equal `"my-app"` / `"my_app"` respectively.

### `[tool.uv.sources]` transitive conflicts

When scaffolded projects depend on multiple kaos-* packages and we
override sources with absolute paths, uv sees the transitive
`[tool.uv.sources]` from the depended-on packages (which use relative
`../kaos-pdf` paths). uv treats these as different URL specs — same
filesystem destination, different specs — and errors:

```
Requirements contain conflicting URLs for package `kaos-pdf` in all
marker environments:
  - file:///abs/path/to/kaos-pdf
  - file:///abs/path/to/kaos-pdf (editable)
```

**Don't fight the resolver.** The kaos-ui integration test replaces
the scaffolded `pyproject.toml` with a minimal install set
(kaos-core + streamlit + pydantic) for testing. The full kaos-*
workspace install path is exercised inside the kaos-modules
workspace where the relative paths in each package's
`[tool.uv.sources]` line up.

When kaos-* packages publish to PyPI, this entire workaround
disappears.

## Streamlit

### Streamlit pages are top-level scripts — no `return`

Streamlit page files (`pages/chat.py`, etc.) are executed by the
runtime as a script: their top level is *not* wrapped in a function.
A bare `return` outside a `def` is a `SyntaxError` at compile time.

`ast.parse()` *accepts* this (it's a semantic, not grammatical,
error). `compile(source, filename, "exec")` rejects it. The kaos-ui
integration test runs both — see `tests/integration/test_template_compiles.py`.

To halt early in a page, use `st.stop()`:

```python
try:
    asyncio.run(_run())
except Exception as exc:
    st.error(f"Error: {exc}")
    st.stop()  # NOT `return`
```

### `services/*` should lazy-import KAOS extras

The Streamlit chat service imports `kaos_agents` only inside function
bodies. Module-level imports get triggered the moment a page does
`from {slug}.services import chat as chat_service`, which happens at
page navigation in `st.navigation`. With kaos-agents missing (or
broken), the entire page fails — even pages that don't use chat.

Same rule across templates: every `services/*.py` lazy-imports
optional KAOS deps. The screen / page / route imports the service
module cheaply; only function calls trigger heavy deps.

### `AppTest` does not fully render `st.navigation` apps

[streamlit/streamlit#9446](https://github.com/streamlit/streamlit/issues/9446)
is open. `AppTest.from_file("app.py")` against an entrypoint that calls
`st.navigation()` renders only the entrypoint, not the selected page.

Workarounds:

1. **Test pages individually** by pointing `AppTest.from_file()` at the
   page file (`pages/chat.py`) directly. Each page imports
   `st.session_state["settings"]`, so the test's autouse fixture must
   prime that.
2. The `app.py` smoke test exists to catch import-time failures, not
   page rendering. Don't assert on page content from it.

Once `#9446` lands, both paths converge and the per-page tests can
collapse into the app.py test.

### Bound every cache

`@st.cache_resource` and `@st.cache_data` MUST pass explicit `ttl=` and
`max_entries=`. Unbounded caches are the #1 OOM cause in Streamlit
deployments. The runtime singleton uses
`@st.cache_resource(ttl=3600, max_entries=1)`.

### `magicEnabled = false`

Streamlit defaults `magicEnabled = true`, which makes bare expressions
auto-render via `st.write()`. Vibe coders pasting debug expressions
silently leak them to the UI. Templates explicitly set this off.

### `showErrorDetails = "none"`

Streamlit defaults `showErrorDetails = "full"` — tracebacks (and
secrets in tracebacks) leak to the browser. Templates set
`"none"` (string, not boolean) for production safety.

### `enableCORS=False` + `enableXsrfProtection=False` is a footgun

Setting both off is rejected by Streamlit. Setting one off without the
other re-enables both silently in newer versions. Templates leave both
on; CORS allowlist is empty (no cross-origin) which is correct for
localhost or behind-a-proxy deployments.

### Streamlit cannot inject HTTP security headers

Streamlit's response pipeline doesn't expose a hook for Content-Security-
Policy / HSTS / X-Frame-Options. Templates ship a Caddyfile so that the
reverse proxy injects the headers in production. Don't try to "fix"
this in the Streamlit app itself.

## File uploads

### Magic-byte verification beats extension-only

Streamlit's `st.file_uploader(type=...)` is enforced **client-side
only**. Server-side, validate that the file's content matches its
declared extension via `python-magic` (or equivalent libmagic binding).
The template's `services/uploads.py:_verify_magic_bytes` does this and
falls back to a logged warning when libmagic is unavailable on the
host (developer machines without `libmagic1` still work; production
deployments should install it).

Renaming `evil.exe` to `payroll.pdf` is the single most common upload
attack vector. Reject before any parser touches the bytes.

### Document IDs must be path-safe

`_make_document_id` returns a sha256 hex digest (truncated to 12 chars).
This is collision-resistant for low volumes, contains no path
separators or NUL bytes, and survives directory naming. **Do not** use
the user's filename as a directory name even after sanitization —
sha256 + nanosecond timestamp is the right choice.

## Testing templates

### `ast.parse` is necessary but not sufficient

Templates ship `.py.tmpl` files with `{{KAOS_*}}` placeholders that
are not valid Python until rendered. The kaos-ui integration test
scaffolds each kind into a tmpdir and AST-parses every emitted `.py` to
catch syntax bugs at our test time — not at the user's scaffold time.

But `ast.parse` catches only syntax errors. To catch import-time
errors, name errors, and broken imports, the integration test ALSO
swaps in a minimal `pyproject.toml`, runs `uv sync`, and runs the
scaffolded project's deterministic tests (settings, auth, uploads).
Both gates are required.

### Cross-file consistency

`.python-version`, `pyproject.toml [project] requires-python`, and the
Dockerfile's `PYTHON_VERSION` build arg must agree. The integration
test asserts this; without it, a fresh-cache `uv sync` fails on a
mismatch nobody noticed locally.

## Textual

### `_render` is reserved on Widget — pick a different name

`textual.widget.Widget._render()` is part of Textual's render pipeline.
Overriding it on a `Screen` subclass silently breaks rendering — the
internal `Widget.visual` becomes `None` and Textual raises:

```
.venv/lib/.../textual/visual.py:227 in to_strips
    strips = visual.render_strips(...)
AttributeError: 'NoneType' object has no attribute 'render_strips'
```

Caught the kaos-ui Textual chat screen on first integration test run.
Rule: widget-internal helpers never use `_render`. Prefer
`_refresh_*`, `_update_*`, `_apply_*`. The Streamlit template uses
`_render` freely (Streamlit has no such reserved method); this only
applies to Textual.

### `App.run_test()` works in CI without a TTY

Textualize themselves note in [discussion #166](https://github.com/Textualize/textual/discussions/166)
that `App.run(headless=True)` "doesn't catch errors" — `App.run_test()`
does. Always use `run_test`. The Pilot context manager handles teardown
correctly even when assertions fire.

### `screen.id` is None unless explicitly set

`SCREENS = {"chat": ChatScreen, ...}` registers screens by name but
does not set `screen.id` on instances. Tests that want to identify the
current screen use `isinstance(app.screen, ChatScreen)`, not
`app.screen.id`.

### `Markdown.get_stream()` is the canonical streaming pattern

But fragile against chunk boundaries that split markdown syntax
(`**bold**` arriving as two events). The kaos-ui chat screen uses a
"rebuild the buffer per token" approach via `Markdown.update(...)` —
robust against partial markdown, no reach into widget private state.

### TUI logging: file handler with `propagate=False`

Textual owns stdout/stderr while running. Console-bound logging
corrupts the rendered UI. The kaos-ui Textual template ships a JSON
`RotatingFileHandler` and sets `propagate=False` on the `kaos.*`
logger root so KAOS module logs don't leak to Textual's own
`TextualHandler` if it's attached.

### Free-threaded Python 3.14t breaks Playwright sync API

`playwright.sync_api` uses greenlets, which interact badly with
Python 3.14's free-threaded GIL: tests fail with
``Fatal Python error: PyMutex_Unlock: unlocking mutex that is not locked``.

Use the async API:

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/google-chrome")
        ...

asyncio.run(main())
```

This affects test harnesses run from kaos-ui itself (3.14t default),
not scaffolded projects (which can use whichever Python they pin).

## SPA / web

### Auth context: React `setState` is async — return values directly

The naive `AuthContext.refresh()`:

```python
const refresh = useCallback(async () => {
    const response = await apiFetch("/v1/auth/me");
    setAuthed(response.ok);  // queued, not yet flushed
}, []);
```

…breaks router auth gates. The TanStack Router `_auth.beforeLoad`
runs synchronously after `await refresh()`. It reads
`context.auth.isAuthenticated` (the React-state copy) — which is
*still false* because the state update queued by `setAuthed` hasn't
flushed yet on the same microtask tick.

Result: cookie is set, /v1/auth/me returns 200, but the next
navigation gets redirected back to /login.

Fix: return the result directly *and* mirror in a ref for synchronous
reads:

```ts
const refresh = useCallback(async (): Promise<boolean> => {
    const response = await apiFetch("/v1/auth/me");
    const ok = response.ok;
    authedRef.current = ok;
    setAuthed(ok);
    return ok;
}, []);
```

Then in the route guard:

```ts
beforeLoad: async ({ context }) => {
    if (context.auth.isAuthenticated) return;
    const ok = await context.auth.refresh();  // ← read the boolean, not the state
    if (!ok) throw redirect({ to: "/login" });
}
```

### Vite proxy port: read from env, never hardcode

Templates default `VITE_BACKEND_URL` to `http://127.0.0.1:8000` but
read the env var first. Multi-tenant dev hosts that already have :8000
occupied (other agent sessions, other projects) would otherwise see
the dev proxy forward to the wrong backend and serve unexpected
content. The override is documented in CLAUDE.md.

### Vite build script ordering: don't `tsc -b` before `vite build`

`tsc -b && vite build` fails on a fresh checkout because TanStack
Router's plugin generates `routeTree.gen.ts` *during* vite's run,
not before. The naive build script crashes with:

```
src/main.tsx: Cannot find module './routeTree.gen' or its corresponding type declarations.
src/routes/_auth.tsx: Argument of type '"/_auth"' is not assignable to parameter of type 'undefined'.
```

Templates use `vite build` for the build script (vite + plugin-react
handle TS transforms). A separate `typecheck` script runs `vite build
--mode development` first to seed `routeTree.gen.ts`, then `tsc
--noEmit`.

### `vitest/config` for type-checked test config

`vite.config.ts` with a `test:` block fails type checking unless you
import `defineConfig` from `vitest/config` instead of `vite`. The
former re-exports vite's defineConfig with the vitest extension.

## kaos-agents

### `Agent` is config; `Runner` is execution

Don't try to construct a `Runner` directly with `instructions=` /
`model=` keyword arguments — those go on `Agent`. The pattern is:

```python
agent = Agent(
    instructions=...,
    pattern=AgentPattern.CHAT,
    model=f"{provider}:{model}",
    tools=("kaos-*",),
)
runner = Runner(agent, runtime=runtime)
async for event in runner.run(message, session_id):
    ...
```

`SessionMemory` lives in `SessionStore(vfs).load_or_create(session_id)`,
NOT as a `Runner` constructor argument. Memory persists across runs
because the same `session_id` lookup hits the same VFS path.

### Stream tokens come from `TextDelta.content`, NOT `.text`

`async for event in runner.run(...)` yields 19 typed event subclasses.
The streamed assistant token chunk is on `TextDelta.content`, while
the assembled final response on `TurnComplete.text` is the FULL
message at the end. Reading `.text` on `TextDelta` returns `None`
silently — no exception, just empty assistant messages in the UI.

Always filter by `isinstance` AND read the canonical field:

```python
from kaos_agents import TextDelta
async for event in runner.run(...):
    if isinstance(event, TextDelta):
        accumulated.append(event.content)  # NOT .text
```

`getattr(event, "text", None)` is a triple footgun: it matches
`TurnComplete` too (so you get the final string twice — once as a
delta-shaped event and once when the turn ends), it picks up
`ThinkingDelta` if any future event grows a `text` attribute, and it
silently returns `None` on `TextDelta`.

### Don't roll your own SSE parser — use `eventsource-parser`

The SPA template uses `sse-starlette` server-side, which emits CRLF
event separators (`\r\n\r\n`). A naive client parser using
`buffer.indexOf("\n\n")` finds nothing, the SSE stream "succeeds"
(HTTP 200, body fully read), and the consumer's `for await` exits
without yielding a single event. The chat UI shows an empty assistant
message and no error. This bug bit the template once and is hard to
spot because the unit tests used LF-only fixtures.

The 2026 standard is **`eventsource-parser`** (Vercel-maintained,
~3M weekly downloads, used by the Vercel `ai` SDK, OpenAI Node SDK,
and Anthropic SDK). It's a state-machine parser that handles CRLF/CR/LF
separators, multi-line `data:` accumulation, comment lines, `event:`
/ `id:` / `retry:` fields, UTF-8 BOMs, and chunk boundaries that
split events. We keep our own `fetch()` (so we control credentials,
abort, request body) but the parsing layer must be the library.

Regression tests in `apps/spa/tests/streaming.test.ts` lock in:
1. CRLF-terminated events (matching `sse-starlette`'s wire format)
2. Events split across chunk boundaries mid-UTF-8

Both must keep passing. If a future change "just" tweaks the parser,
ask: would `eventsource-parser` already do this? Almost always yes.

Native `EventSource` is wrong for our chat use case because it can't
do POST / custom headers / cookie auth the way we need; that's why
we use `fetch` + `eventsource-parser` instead.
