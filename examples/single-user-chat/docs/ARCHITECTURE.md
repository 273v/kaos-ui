# single-user-chat — Architecture

> Status: draft. Last updated: 2026-05-14. Verified against PyPI installs of `kaos-agents==0.1.0a1`, `kaos-core==0.1.0a6`, `kaos-llm-client==0.1.0a3`. Read `PRD.md` and `UX-LANGUAGE.md` first.

## 1. System overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Browser (single user)                         │
│                                                                            │
│   ┌──────────────────┐    ┌──────────────────┐    ┌───────────────────┐   │
│   │  /login          │    │  /sessions       │    │  /sessions/:id    │   │
│   │  TanStack Router │    │  list + new      │    │  chat + drawer    │   │
│   └────────┬─────────┘    └────────┬─────────┘    └────────┬──────────┘   │
│            │                       │                       │              │
│            └───────────────────────┼───────────────────────┘              │
│                                    │                                      │
│                       apps/spa/src/lib/api-fetch.ts                       │
│                       apps/spa/src/lib/streaming.ts (readSseStream)       │
│                                    │                                      │
│                fetch + eventsource-parser + credentials: include          │
└────────────────────────────────────┼───────────────────────────────────────┘
                                     │ TLS via Caddy (flush_interval -1)
┌────────────────────────────────────┼───────────────────────────────────────┐
│                              FastAPI backend                              │
│                                    │                                      │
│  ┌───────────────────────────── /v1 ────────────────────────────────────┐ │
│  │                                                                     │ │
│  │  /v1/sessions/...           ← kaos_agents.api.server.create_app()   │ │
│  │  /v1/sessions/{id}/messages   (POST, GET, DELETE, SSE, memory)      │ │
│  │  /v1/runs/{id}/approve        (auto + bearer auth + CORS + OpenAPI) │ │
│  │                                                                     │ │
│  │  /v1/models                 ← OUR routers/models.py                 │ │
│  │  /v1/chat/sessions          ← OUR routers/chat.py                   │ │
│  │  /v1/chat/sessions/{id}/meta                                        │ │
│  │  /v1/chat/sessions/{id}/messages   (proxy + metadata threading)     │ │
│  │  /v1/chat/sessions/{id}/transcript                                  │ │
│  │                                                                     │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Bearer auth via KAOS_AGENTS_API_TOKEN. CORS via                         │
│  KAOS_AGENTS_API_CORS_ALLOW_ORIGINS. Both enforced by kaos-agents.        │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │ HTTPS
                          LLM provider (Anthropic / OpenAI / …)


┌────────────────────────────────────────────────────────────────────────────┐
│                    Local disk — kaos VirtualFileSystem                     │
│                                                                            │
│   .kaos-vfs/                                                               │
│   ├── single-user-chat/                                                    │
│   │   └── sessions/{id}/meta.json     ← OUR metadata sidecar               │
│   │                                     {title, model, system_prompt,      │
│   │                                      tools_enabled, created_at,        │
│   │                                      last_message_at, archived}        │
│   │                                                                        │
│   └── kaos-agents/sessions/{id}/       ← managed by kaos-agents             │
│       ├── memory.json                  ← SNAPSHOT mode sections            │
│       ├── messages.jsonl               ← MESSAGES stream                    │
│       ├── actions.jsonl                ← ACTIONS stream                     │
│       └── graph.ttl                    ← GRAPH section (RDF turtle)         │
└────────────────────────────────────────────────────────────────────────────┘
```

## 2. Repository layout

```
kaos-ui/examples/single-user-chat/
├── README.md
├── Makefile                              # install / sync-ui / dev / test / up / down / doctor
├── docker-compose.yml                    # backend + caddy + spa-build
├── docker-compose.postgres.yml           # parity — unused in v1
├── Caddyfile                             # TLS + flush_interval -1 for SSE
├── pnpm-workspace.yaml                   # packages: ./packages/* ./apps/*
├── package.json                          # root scripts only
├── .env.example
├── .gitignore                            # ignores packages/ui/ (sync-generated)
├── .pre-commit-config.yaml
│
├── scripts/
│   └── sync-ui.sh                        # stamps packages/ui from the web:spa template
│
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md                   # this file
│   ├── PLAN.md
│   ├── UX-LANGUAGE.md                    # visual + interaction spec
│   └── PATTERNS.md                       # gotchas discovered during build
│
├── packages/
│   └── ui/                               # GENERATED — gitignored, run `make sync-ui` to populate
│       └── ...                           # mirror of templates/web/spa/packages/ui with placeholders rendered
│
├── apps/
│   └── spa/
│       ├── package.json                  # @kaos-chat-example/spa
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── biome.json
│       ├── index.html
│       ├── openapi-ts.config.ts
│       ├── tests/
│       └── src/
│           ├── main.tsx
│           ├── styles/                   # @import "@kaos-chat-example/ui/styles/globals"
│           ├── auth/                     # context + storage
│           ├── api/
│           │   └── client/               # generated by openapi-ts (gitignored)
│           ├── lib/
│           │   ├── api-fetch.ts          # copied verbatim from template
│           │   ├── streaming.ts          # copied verbatim from template
│           │   ├── event-handler.ts      # exhaustive dispatch on the kaos-agents wire taxonomy
│           │   ├── markdown.ts           # markdown-it w/ link sanitization
│           │   └── transcript.ts         # client-side Markdown / JSON serializers
│           ├── components/
│           │   ├── chat/                 # Composer, Message, TurnStatus, UsageChip, ToolCallBlock, RightRail
│           │   ├── sessions/             # SessionList, SessionListItem, NewChatButton
│           │   ├── settings/             # SettingsSheet, ModelPicker, PromptEditor
│           │   └── layout/               # AppShell, Sidebar, Header
│           ├── hooks/
│           │   ├── use-session-list.ts
│           │   ├── use-session.ts
│           │   ├── use-send-message.ts   # owns the SSE stream
│           │   └── use-models.ts
│           └── routes/
│               ├── __root.tsx
│               ├── index.tsx             # → /sessions
│               ├── login.tsx
│               ├── _auth.tsx             # auth gate
│               ├── _auth.sessions.tsx    # list
│               └── _auth.sessions.$id.tsx  # detail
│
└── backend/
    ├── pyproject.toml                    # real file (no placeholders); PyPI-verified pins
    ├── README.md
    ├── Dockerfile                        # lifted from web:spa, multi-stage, non-root user
    ├── tests/
    │   ├── unit/
    │   └── integration/
    └── app/
        ├── __init__.py
        ├── main.py                       # mounts create_app() + extension routers
        ├── settings.py                   # AppSettings (env_prefix="APP_")
        ├── deps.py
        ├── logging_setup.py              # configure + app_logger
        ├── exceptions.py                 # AppError hierarchy
        ├── models.py                     # API contracts (pydantic models)
        ├── persistence/
        │   ├── __init__.py
        │   └── sessions.py               # metadata sidecar CRUD against meta.json
        ├── routers/
        │   ├── __init__.py
        │   ├── health.py                 # GET /v1/_health (kaos-agents already has its own)
        │   ├── models.py                 # GET /v1/models — static catalog
        │   └── chat.py                   # /v1/chat/* — sessions list, meta, proxy stream, transcript
        └── services/
            ├── __init__.py
            ├── catalog.py                # MODELS list (verified from MODEL_PRICING)
            └── stream_proxy.py           # internal SSE re-stream helper for /v1/chat/sessions/{id}/messages
```

### packages/ui consumption — the sync-on-install strategy

The template's `packages/ui/package.json` declares `"name": "@{{KAOS_NPM_SLUG}}/ui"` — an unrendered Jinja placeholder. A workspace ref at `../../templates/web/spa/packages/ui` therefore won't resolve.

`scripts/sync-ui.sh` solves this at install time:

```bash
#!/usr/bin/env bash
# Stamps packages/ui from templates/web/spa/packages/ui with placeholders rendered.
set -euo pipefail

NPM_SLUG="kaos-chat-example"
PROJECT_NAME="Single-User Chat"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/../../kaos_ui/templates/web/spa/packages/ui"
DST="$ROOT/packages/ui"

rm -rf "$DST"
cp -r "$SRC" "$DST"

# Substitute the only placeholder that appears in packages/ui sources.
find "$DST" -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.css' -o -name '*.json' \) \
  -exec sed -i "s/{{KAOS_NPM_SLUG}}/$NPM_SLUG/g" {} +
find "$DST" -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.css' -o -name '*.json' \) \
  -exec sed -i "s/{{KAOS_PROJECT_NAME}}/$PROJECT_NAME/g" {} +

echo "Synced packages/ui from $SRC"
```

`packages/ui/` is `.gitignore`d. `make install` runs `sync-ui` as a prereq. The README documents: "Do not edit `packages/ui/` directly — edit the template at `kaos_ui/templates/web/spa/packages/ui/` and re-run `make sync-ui`."

Trade-offs vs. alternatives:
- Vendor a checked-in stamped copy → drifts on every template update.
- Add a `kaos-ui stamp-ui` subcommand → cleaner but blocks Phase 0 on a kaos-ui feature.

## 3. API contract

All routes under `/v1`. JSON bodies. Bearer auth via `Authorization: Bearer $KAOS_AGENTS_API_TOKEN` (or the cookie set by `/v1/chat/auth/login` — see § 4.5). Errors follow `{error: {what, how_to_fix, alternative?}}` per `kaos-modules/CLAUDE.md` § Agent-friendly errors. The kaos-agents-owned routes follow kaos-agents' error shape; our routes match.

### 3.1 Kaos-agents-owned routes (mounted by `create_app()`)

| Method | Path | Source |
|---|---|---|
| POST | `/v1/sessions` | kaos-agents |
| GET | `/v1/sessions/{id}` | kaos-agents |
| DELETE | `/v1/sessions/{id}` | kaos-agents |
| POST | `/v1/sessions/{id}/messages` | kaos-agents (SSE) |
| GET | `/v1/sessions/{id}/memory/{section}` | kaos-agents |
| POST | `/v1/sessions/{id}/memory/search` | kaos-agents |
| POST | `/v1/runs/{run_id}/approve` | kaos-agents |
| GET | `/openapi.json`, `/docs`, `/redoc` | kaos-agents |

These are not in our codebase. We don't document their shapes in detail here — the SPA gets them via the generated OpenAPI client.

### 3.2 Our extension routes (`/v1/models`, `/v1/chat/*`)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/v1/models` | — | `{models: ModelEntry[]}` |
| GET | `/v1/chat/sessions` | — query: `?limit=50&cursor=…&archived=false` | `{sessions: SessionSummary[], next_cursor: str \| null}` |
| GET | `/v1/chat/sessions/{id}/meta` | — | `SessionMeta` |
| PATCH | `/v1/chat/sessions/{id}/meta` | `{title?, model?, system_prompt?, tools_enabled?}` | `SessionMeta` |
| POST | `/v1/chat/sessions/{id}/messages` | `{message: str}` | `EventSourceResponse` — proxy stream |
| GET | `/v1/chat/sessions/{id}/transcript` | — query: `?format=markdown\|json` | text/markdown or application/json |
| POST | `/v1/chat/sessions/{id}/archive` | — | `{ok: true, archived_at}` |
| GET | `/v1/chat/categories` | — | `{categories: CategoryInfo[]}` (TR-4) |
| PATCH | `/v1/chat/sessions/{id}/tool-set` | `{allowed_groups?, denied_tools?, auto_narrow?}` | `SessionMeta` (TR-4) |
| GET | `/v1/chat/sessions/{id}/files` | — | `{files: FileMeta[]}` (P1-2) |
| POST | `/v1/chat/sessions/{id}/files` | multipart | `{file: FileMeta, tools_enabled}` (P1-1) |
| GET | `/v1/chat/sessions/{id}/files/{name}/download` | — | binary (FEAT-5) |
| DELETE | `/v1/chat/sessions/{id}/files/{name}` | — | 204 |
| POST | `/v1/chat/sessions/{id}/files:backfill` | `{overwrite?, filename?}` | `{updated: int}` (FIX-2) |
| POST | `/v1/chat/sessions/{id}/citations` | `{text}` | `{citations[], count}` (P2-1) |

### 3.3 Pydantic shapes

```python
class ModelEntry(BaseModel):
    id: str                            # "provider:model"
    label: str                         # human-friendly name
    provider: Literal["anthropic", "openai", "google", "xai"]
    context_window: int | None = None
    recommended_for: str | None = None

class SessionToolSetWire(BaseModel):
    # TR-3: per-session tool ceiling. allowed_groups bounds the
    # planner's per-turn choice; denied_tools is the hard floor.
    allowed_groups: list[str] = Field(
        default_factory=lambda: ["documents", "citations", "vfs"]
    )
    denied_tools: list[str] = Field(default_factory=list)
    auto_narrow: bool = True

class SessionMeta(BaseModel):
    id: str                            # ULID, shared with kaos-agents session_id
    title: str
    model: str                         # "provider:model"
    system_prompt: str
    tool_set: SessionToolSetWire       # TR-3 — source of truth
    tools_enabled: bool                # @computed_field, = not tool_set.is_blocking_all
    created_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0
    archived: bool = False
    starred: bool = False
    title_source: Literal["manual", "auto"] = "auto"
    title_updated_at: datetime | None = None

class SessionSummary(BaseModel):
    id: str
    title: str
    model: str
    last_message_at: datetime | None
    created_at: datetime
    message_count: int
    archived: bool = False
```

History rehydration on `/sessions/:id` route load is two calls in parallel:
1. `GET /v1/chat/sessions/{id}/meta` — fast, our metadata.
2. `GET /v1/sessions/{id}` — kaos-agents-native, returns session state including the MESSAGES section.

### 3.4 Metadata threading on stream

**Verified pre-flight (2026-05-14):** kaos-agents `MessageRequest` accepts per-turn `model`, `instructions`, `tools`, `pattern`, `max_cost_usd`, `require_approval_for_tools`. **Field name is `instructions`, NOT `system_prompt`.** See `PATTERNS.md` P-005.

`POST /v1/chat/sessions/{id}/messages` proxies to kaos-agents over HTTP:

```python
@router.post("/{session_id}/messages")
async def send(session_id: str, body: SendMessageBody, request: Request):
    meta = session_store.get(session_id)
    forward_body = {
        "message": body.message,
        "model": meta.model,
        "instructions": meta.system_prompt,       # note: kaos-agents calls this "instructions"
        "tools": ["*"] if meta.tools_enabled else ["kaos-core-*"],
        "max_cost_usd": settings.turn_budget_usd,
    }
    return EventSourceResponse(stream_proxy(session_id, forward_body, bearer_token=...))
```

`stream_proxy` is `httpx.AsyncClient.stream("POST", upstream_url, headers={Authorization, Accept: text/event-stream}, json=forward_body)` — see `services/stream_proxy.py`. After the stream completes, the proxy bumps `meta.last_message_at` and `meta.message_count` in our sidecar.

**Why HTTP-forward instead of in-process `Runner.run()`?** Per-turn overrides on the wire mean we don't need to construct an Agent ourselves — kaos-agents builds it from the body. Less coupling to kaos-agents internals. The HTTP hop is on localhost; latency is negligible vs. the LLM round-trip.

### 3.5 Per-turn latency budget (DOC-3)

End-to-end target for a tool-able turn with `auto_narrow=True`:

| Stage | Typical | Notes |
|---|---|---|
| `IntentExtractor` (kaos-agents) | ~1.5s | Haiku classify "TOOL_USE vs RESPOND" |
| `TurnToolPolicy` planner (TR-5) | ~1.1s | Haiku narrow categories; cost ~$0.001 |
| ReAct LLM call(s) | 2–10s | The expensive step; bounded by `APP_TURN_BUDGET_USD` |
| Tool execution | 0.1–8s | Depends on the tool (Federal Register search is ~1.5s remote) |
| `turn_summary` emit + meta touch | <50ms | Pure local write |
| **End-to-end p50** | 5–8s | One tool call + one LLM round trip |
| **End-to-end p95** | 12–18s | Two ReAct iterations + slow tool |

Provider transport is `pydantic-ai-slim` via `kaos-llm-client`. `kaos-source` connectors gated through `SessionToolSet.allowed_groups` at the proxy (TR-2); the agent never sees a denied tool. Auto-title (POL-B) uses a separate `kaos-llm-core.programs.summarize_session_title` Call (Haiku default; configurable via `APP_AUTO_TITLE_MODEL`); `title_source` flips from "auto" to "manual" the moment the user renames a session via PATCH /meta.

## 4. Backend internals (extension layer)

### 4.1 main.py

```python
# backend/app/main.py
from fastapi import FastAPI
from kaos_agents.api.server import create_app as create_agent_app

from app.routers import chat, health, models
from app.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings()
    # kaos-agents reads KAOS_AGENTS_API_* env vars to configure auth + CORS.
    base = create_agent_app()
    base.state.app_settings = settings

    base.include_router(health.router, prefix="/v1")
    base.include_router(models.router, prefix="/v1")
    base.include_router(chat.router, prefix="/v1/chat")
    return base


app = create_app()
```

That's the whole entrypoint. No custom lifespan, no custom CORS, no custom auth middleware.

### 4.2 settings.py

```python
class AppSettings(BaseSettings):
    """Example-specific settings. kaos-agents-owned settings live in KAOS_AGENTS_API_*."""

    env: Literal["development", "production", "test"] = "development"

    # Defaults used when a new session is created without explicit overrides.
    # Audience is attorneys; default to a frontier reasoning tier. Do NOT
    # downshift to "haiku" / "mini" / "nano" — see docs/PRD.md § 6.
    default_model: str = "anthropic:claude-opus-4-7"
    default_system_prompt: str = DEFAULT_INSTRUCTIONS
    default_tools_enabled: bool = False
    turn_budget_usd: float = 0.50

    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=".env", extra="ignore",
    )
```

Note env literal: `"development"` not `"dev"`, matching the template (verified at `templates/web/spa/backend/app/settings.py.tmpl:29`).

We do **not** redeclare `KAOS_AGENTS_API_TOKEN`, CORS origins, etc. — they live in kaos-agents' own settings (`KaosAgentsAPISettings`). `.env.example` documents both blocks side by side.

### 4.3 Tool policy — registry + per-session ceiling + per-turn planner

The example demonstrates **two layers** of tool gating on top of
kaos-agents:

```
SettingsSheet (TR-8)
  ├─ PATCH /v1/chat/sessions/:id/tool-set        (TR-4)
  │     ↓
  │  SessionMeta.tool_set  (TR-3, persisted)
  │  { allowed_groups, denied_tools, auto_narrow }
  │     ↓
  │  (read at every turn)
  │     ↓
TurnToolPolicy Program  (TR-5, optional per-turn narrowing)
  ↓
  effective_tool_set = ceiling ∩ planner_groups
  ↓
filter_tools(runtime.tools, SessionToolSet)       (TR-2)
  ↓
kaos-agents Runner sees ONLY the narrowed catalog
  ↓
tool_policy_decided SSE event           (TR-7, transparency)
  ↓
<ToolPolicyBadge> above the assistant message  (TR-9)
+ <CostStrip> "Planner" row             (TR-10)
```

Tool groups are partitioned by kaos-ui's
`register_kaos_tool_groups(runtime)` (TR-1) which runs at app
startup after every `register_*_tools` call. The four shipped
groups (`web`, `documents`, `citations`, `vfs`) live in
`kaos_agents.registry.default_tool_group_registry` so that
`kaos_agents.context.filter_tools` can resolve a SessionToolSet
against them.

The `auto_narrow` planner (TR-5) is a single kaos-llm-core
`Call` (Haiku by default, configurable via `APP_TURN_POLICY_MODEL`).
Cost target ≤ $0.0002/turn, latency p95 ≤ 300ms; the planner
abdicates to the full ceiling when its confidence is below 0.6
(`APP_TURN_POLICY_CONFIDENCE_THRESHOLD`). Refusing to narrow is
always safe — false narrowing wastes a turn, false broadening
costs at most a few cents of prompt tokens.

The `denied_tools` floor in SessionToolSetWire is the security
boundary — write tools (`kaos-office-write-*`) are never bridged,
even when the user enables every group. Promotion of this Program
into `kaos_agents.planning.policy` is the followup; until then
the example carries the lone implementation.

### 4.4 The chat proxy router

```python
# backend/app/routers/chat.py
from fastapi import APIRouter, Depends, Request
from sse_starlette import EventSourceResponse

from app.persistence.sessions import SessionStore, get_session_store
from app.services.stream_proxy import stream_via_runner

router = APIRouter(tags=["chat"])


@router.get("/sessions")
async def list_sessions(
    store: Annotated[SessionStore, Depends(get_session_store)],
    limit: int = 50,
    cursor: str | None = None,
    archived: bool = False,
) -> dict:
    items, next_cursor = store.list(limit=limit, cursor=cursor, archived=archived)
    return {"sessions": items, "next_cursor": next_cursor}


@router.get("/sessions/{sid}/meta")
async def get_meta(sid: str, store: Annotated[...]) -> SessionMeta:
    return store.get(sid)


@router.patch("/sessions/{sid}/meta")
async def patch_meta(sid: str, body: PatchMetaBody, store: Annotated[...]) -> SessionMeta:
    return store.patch(sid, **body.model_dump(exclude_unset=True))


@router.post("/sessions/{sid}/messages")
async def send_message(
    sid: str,
    body: SendMessageBody,
    request: Request,
    store: Annotated[...],
) -> EventSourceResponse:
    meta = store.get(sid)
    runtime = request.app.state.agent_runtime   # from create_app's app.state
    return EventSourceResponse(
        stream_via_runner(meta, runtime, message=body.message),
        ping=15,
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{sid}/transcript")
async def transcript(sid: str, format: Literal["markdown", "json"] = "markdown", ...) -> Response:
    ...
```

### 4.5 Stream service

```python
# backend/app/services/stream_proxy.py
from typing import AsyncIterator
import httpx

from app.models import SessionMeta


async def stream_proxy(
    session_id: str,
    forward_body: dict,
    *,
    upstream_url: str,
    bearer_token: str,
) -> AsyncIterator[dict]:
    """HTTP-forwards to kaos-agents' /v1/sessions/{id}/messages with our metadata applied."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{upstream_url}/v1/sessions/{session_id}/messages",
            headers={
                "Authorization": f"Bearer {bearer_token}",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            json=forward_body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line.startswith("data: "):
                    data = line[len("data: "):]
                    yield {"event": event_type, "data": data}
                # blank lines + comments ignored
```

The upstream URL is `http://127.0.0.1:8000` (same process, same port — FastAPI handles the loopback). Bearer token comes from `os.environ["KAOS_AGENTS_API_API_TOKEN"]` (note the double `API_` — see `PATTERNS.md` P-001).

`CostTrackingHook` is **not** installed — `UsageObserved` events already carry `total_tokens` and `cost_usd` per turn (verified). The hook is only needed for cross-turn rollups, which v1 doesn't show. **Note:** because we HTTP-forward rather than run `Runner` in-process, we can't attach our own hooks anyway — kaos-agents builds the Runner on its side. That's fine for v1.

### 4.5 Auth

Bearer auth ships with `create_app()`. The token is `KAOS_AGENTS_API_TOKEN`, settings-driven, refuses `< 32` chars in production. We do not write our own middleware.

For the SPA, two equivalent paths:
- (a) The SPA sends `Authorization: Bearer …` directly. Simple, but the bearer lives in localStorage — soft target for XSS.
- (b) A thin `/v1/chat/auth/login` route on our side takes the bearer in a JSON body and sets it back as an httpOnly cookie. The kaos-agents API itself doesn't have native cookie support; we'd need to wrap its dependency-injected auth. **Defer to Phase 1**; (a) is the v1 baseline.

### 4.6 Session metadata storage

`backend/app/persistence/sessions.py`:

```python
class SessionStore:
    def __init__(self, vfs, namespace="single-user-chat"):
        self._vfs = vfs
        self._ns = namespace

    def _meta_path(self, sid: str) -> str:
        return f"{self._ns}/sessions/{sid}/meta.json"

    def create(self, *, sid: str, title: str, model: str, system_prompt: str,
               tools_enabled: bool) -> SessionMeta: ...
    def get(self, sid: str) -> SessionMeta: ...
    def list(self, *, limit, cursor, archived=False) -> tuple[list[SessionSummary], str | None]: ...
    def patch(self, sid: str, **kwargs) -> SessionMeta: ...
    def archive(self, sid: str) -> None: ...
    def touch(self, sid: str, *, message_count: int | None = None) -> None: ...
```

The store is called by our routes on every mutation. `touch()` is called from `stream_via_runner` when the stream completes, to bump `last_message_at` and `message_count`.

Concurrent-write safety relies on `kaos_core.artifacts.VirtualFileSystem`'s fsync semantics. Single-user means no two writers; no explicit locking needed.

## 5. Frontend internals

See `UX-LANGUAGE.md` for the visual + interaction spec. This section covers wiring only.

### 5.1 Routing

TanStack Router, file-based:

```
src/routes/
├── __root.tsx                   AppShell w/ Sidebar + <Outlet/>
├── index.tsx                    redirect → /sessions
├── login.tsx                    public; bearer-token form
├── _auth.tsx                    auth gate
├── _auth.sessions.tsx           sidebar visible; outlet for detail
└── _auth.sessions.$id.tsx       chat + right rail
```

### 5.2 Data layer

TanStack Query only. Stores:

| Hook | Query key | Role |
|---|---|---|
| `useSessionList()` | `["chat", "sessions"]` | Sidebar list (our extension route). |
| `useSession(id)` | `["chat", "session", id]` | Joined: our `/meta` + kaos-agents `GET /v1/sessions/{id}` for MESSAGES. |
| `useModels()` | `["models"]` | Model picker catalog. |
| `useCreateSession()` | mutation | New-chat button. Calls `POST /v1/sessions` (kaos-agents) then `PATCH /v1/chat/sessions/{id}/meta` with defaults. |
| `usePatchMeta(id)` | mutation | Drawer save. |
| `useArchiveSession(id)` | mutation | Delete (archive). |
| `useSendMessage(id)` | imperative hook owning `AbortController` + the SSE async-iterator | The chat flow. |

Optimistic UX on send: (a) optimistically push the user message into the cached session, (b) push a placeholder assistant message with `streaming: true`, (c) iterate `readSseStream`, (d) per event call into `event-handler.ts` which mutates the cached session in place via `queryClient.setQueryData`, (e) on `turn_summary` finalize the assistant message, (f) on `run_error` replace placeholder with an error variant.

### 5.3 Event handler — the dispatch table

This is the load-bearing table. Implemented in `apps/spa/src/lib/event-handler.ts` as a single discriminated `switch` plus a sub-`switch` for `span.subject × span.phase`. **Every entry below must produce a deliberate render — never a fallthrough.**

The 15 wire types from `kaos_agents.events.ALL_EVENT_TYPES`:

| `event.type` | Carries | UI behavior |
|---|---|---|
| `text_delta` | `content: str` | Append to current assistant message text. Start the streaming caret. |
| `thinking_delta` | `content: str` | Append to a (hidden-by-default) "Reasoning" `<details>` block inside the assistant message. Visible when `?debug=true`. |
| `tool_call_args_delta` | partial JSON args | Append to the current `ToolCallBlock`'s args preview. |
| `span` | `subject`, `phase`, `attributes` | See sub-table below. |
| `intent_classified` | `intent: str`, confidence | Small label above the assistant message: italic, muted. |
| `plan_proposed` | step list | Render a collapsible plan card *above* the response (mostly fires under `AgentPattern.PLAN` — v1 uses CHAT, but we wire the renderer anyway for completeness). |
| `citation_found` | citation record | Append a citation pill to the current message; lazy-add the source to the right-rail Sources list. |
| `usage_observed` | `total_tokens`, `cost_usd`, model id | Update the streaming-message's pending usage state. Render the final `UsageChip` on `turn_summary`. |
| `evidence_insufficient` | reason | Inline warning banner inside the assistant message. |
| `grounding_refusal_triggered` | reason | Inline refusal banner inside the assistant message. |
| `turn_summary` | aggregated final | Finalize the assistant message: stop the streaming caret, set final text + tokens + cost, write back to TanStack Query cache. Bump session `last_message_at`. |
| `memory_event` | `kind: "added"\|"evicted"\|"summarized"\|"hydrated"\|"persisted"\|"searched"` | If `kind === "persisted"`, invalidate `["chat", "sessions"]` (the sidebar might need to update message_count + title). Otherwise debug-only. |
| `run_error` | `what`, `how_to_fix`, `alternative?` | Replace the streaming placeholder with an error-variant message. |
| `budget_exceeded` | `limit_usd`, `spent_usd` | Banner + finalize the streaming message as `[truncated — turn budget exceeded]`. |
| `tool_call_approval_required` | `tool_name`, `args`, `run_state_ref` | v1 stub banner: "Tool call requires approval — UI for this is out of scope in v1. To unblock: disable tools in the session drawer and retry." Show a "Cancel turn" button. |

The `span` sub-switch on `(subject, phase)`:

| `subject` | `phase` | UI behavior |
|---|---|---|
| `turn` | `start` | Set `TurnStatus` to "Thinking…" (italic). |
| `turn` | `complete` / `error` / `cancelled` | Clear `TurnStatus`. Final state comes from `turn_summary` / `run_error`. |
| `step` | `start` | Update `TurnStatus` to `Step N…` if `attributes.step_index` is present. |
| `step` | `complete` / `error` | Demote to debug log; `TurnStatus` updates on next event. |
| `tool_call` | `start` | Render a new `ToolCallBlock` inside the assistant message, status = running, name = `attributes.tool_name`. |
| `tool_call` | `progress` | Append to args preview if `attributes.delta`. |
| `tool_call` | `complete` | Mark block done; show result preview (truncated) + "View in panel" button if large. |
| `tool_call` | `error` | Mark block error; show `attributes.error.what`. |
| `plan` | any | Debug log (`plan_proposed` value event is the user-facing surface). |
| `subagent` / `handoff` | any | Debug log (v1 uses single Agent; these don't fire under CHAT pattern). |

A unit test enumerates every row above, dispatches a synthetic event, and asserts a non-empty render.

### 5.4 Streaming abort

`useSendMessage` exposes `abort()` which calls `AbortController.abort()` on the `signal` plumbed into `readSseStream`. The backend's `EventSourceResponse` will detect the disconnect. **However**: per kaos-agents 0.1.0a1 verification, there's no mid-turn cancellation API on the Runner — it runs to completion on the current turn. We show a "Stopping…" chip until the next turn boundary, then "Stopped." Document this caveat in `docs/PATTERNS.md` once Phase 1 confirms behavior.

### 5.5 Composer chips + model picker

Per `UX-LANGUAGE.md` § 4.3: chip row above the textarea has a model-picker chip and a disabled attach chip. The picker renders a popover with the catalog from `useModels()`. Selecting a model dispatches `usePatchMeta({model})` immediately — applies to the next turn.

### 5.6 Settings sheet

Right-side `Sheet`, triggered from the bottom-left avatar in the sidebar. Contains: model default (override per session), system-prompt textarea, theme toggle, tools toggle, API-key status badges (read-only — derived from `GET /v1/health` if we surface that, or just from a fixed list).

### 5.7 Transcript export

Pure client (also implemented server-side at `/v1/chat/sessions/{id}/transcript` for shareable links). Markdown shape per `UX-LANGUAGE.md` § 4.x, JSON shape mirrors the API contract.

## 6. Persistence design

```
.kaos-vfs/
├── single-user-chat/
│   └── sessions/
│       ├── 01H8XYZ.../meta.json
│       └── archived/
│           └── 01H8ABC.../meta.json
└── kaos-agents/
    └── sessions/                              # ← note the sessions/ segment
        └── 01H8XYZ/
            ├── memory.json
            ├── messages.jsonl
            ├── actions.jsonl
            ├── findings.jsonl
            └── graph.ttl                      # ← GRAPH section, RDF turtle
```

- The session id is shared. Same ULID names our `meta.json` and the kaos-agents memory directory. This is the join key.
- `meta.json` is the only thing we own. The MESSAGES section is read from kaos-agents via `GET /v1/sessions/{id}` for history rehydration.
- Archive is a move under `archived/`, not a delete.
- A fresh session lists **15 persisted sections** (verified via live `POST /v1/sessions` 2026-05-14): `role, playbooks, plan_examples, messages, actions, documents, findings, plan_history, reflection, lessons, last_intent, working, planning_context, audit, graph`. The `MemoryType` enum has additional values (`last_user_message`, `recent_actions`) that are derived/cached and not separately persisted as SNAPSHOT sections. v1 only reads `messages`. See `PATTERNS.md` P-007.

## 7. Settings hierarchy

Resolved in order, highest first:

1. Explicit overrides via `AppSettings(...)` kwargs
2. `KAOS_AGENTS_API_*` env vars — owned by kaos-agents (token, CORS, etc.)
3. `APP_*` env vars — our example-specific settings
4. Provider legacy keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY` (read by `kaos-llm-client` directly)
5. `.env` file
6. Field defaults

API keys use `SecretStr`. `extra="ignore"`. No `os.environ` reads outside `settings.py`.

`.env.example` documents the two prefixes side by side:

```bash
# kaos-agents API (owned by the bundled FastAPI app)
# IMPORTANT: env var names are DOUBLE 'API_' (pydantic-settings + env_prefix quirk).
# See docs/PATTERNS.md P-001. Kaos-agents' own error message is doc-bugged.
KAOS_AGENTS_API_API_TOKEN=please-generate-a-32-char-random-string-or-more
KAOS_AGENTS_API_API_CORS_ALLOW_ORIGINS=http://localhost:5173
# KAOS_AGENTS_API_API_ALLOW_UNAUTH_LOCALHOST=1   # dev only, refuses non-127.0.0.1

# example-specific defaults
APP_ENV=development
APP_DEFAULT_MODEL=anthropic:claude-opus-4-7
APP_TURN_BUDGET_USD=0.50

# LLM provider keys
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=...
# GOOGLE_API_KEY=...
# XAI_API_KEY=...
```

## 8. Dependencies

### Backend `pyproject.toml`

```toml
[project]
name = "kaos-chat-example-backend"
version = "0.1.0"
requires-python = ">=3.13,<3.15"
dependencies = [
  "kaos-agents>=0.1.0a1,<0.2",
  "kaos-core>=0.1.0a6,<0.2",
  "kaos-llm-core>=0.1.0a7,<0.2",       # NOT transitive in kaos-agents 0.1.0a1
  "kaos-llm-client>=0.1.0a3,<0.2",
  "kaos-content[markdown]>=0.1.0a6,<0.2",
  "kaos-pdf>=0.1.0a2,<0.2",
  "kaos-office>=0.1.0a2,<0.2",
  "fastapi>=0.115,<1.0",
  "uvicorn[standard]>=0.32,<1.0",
  "sse-starlette>=2.1,<3",              # used by our proxy stream
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.8,<3",
  "ulid-py>=1.1,<2",
  "httpx>=0.28,<1",                     # for the proxy route → in-process is preferred; httpx only if Phase 1 picks HTTP-style proxy
]
```

`httpx` may be removed if Phase 1 confirms in-process delegation (importing `Runner` directly) is sufficient — currently in for flexibility.

### Frontend

Identical to the `web:spa` template's `apps/spa/package.json` (React 19.1, TanStack Router 1.120, TanStack Query 5.75, Tailwind v4.1, Biome 2.0, Vitest 3.0, Vite 6.3). Plus:

- `markdown-it@^14` + `@types/markdown-it`
- `date-fns@^3`
- `ulid@^2`

## 9. Differences from the web:spa template

| Concern | web:spa | single-user-chat |
|---|---|---|
| Backend wiring | Hand-rolled FastAPI app + AuthMiddleware + chat router | `kaos_agents.api.server.create_app()` + 2 extension routers |
| Session id | hardcoded `"spa-default"` | server-issued ULID via `POST /v1/sessions` |
| History rehydration | none | `GET /v1/sessions/:id` on route load |
| Sidebar | absent | session list + new-chat button (per UX-LANGUAGE § 4.1) |
| Model picker | absent (env-driven only) | per-session via composer chip + drawer |
| System prompt | hardcoded | per-session via drawer |
| Wire event coverage | 4 of 15 (5 dead branches in the switch — see PRD § 1) | 15 of 15, plus full `span (subject, phase)` cartesian |
| Documents / uploads | scaffolded but stub | removed (out of v1 scope) |
| Routes | `__root`, `login`, `_auth`, `_auth.chat` | adds `_auth.sessions`, `_auth.sessions.$id`; removes `_auth.chat` |
| Persistence | none (memory only) | meta.json + kaos-agents VFS |
| Tool toggle | none | per-session via `Agent.tools` glob (`("*",)` vs `("kaos-core-*",)`) |

## 10. Testing

### Backend (`pytest`)

- `unit/test_persistence.py` — `SessionStore` CRUD round-trip + list pagination + archive.
- `unit/test_catalog.py` — every entry parses as `provider:model`; every model id appears in `kaos_llm_client.cost.MODEL_PRICING` (registry guard test — fails loudly if a model id rots).
- `unit/test_event_serialization.py` — round-trip each of the 15 event classes through `serialize_event` and SSE wrap; assert discriminator is preserved.
- `integration/test_routes.py` — full HTTP roundtrip per extension route using `TestClient`. **Important:** must launch `create_app()` with `KAOS_AGENTS_API_ALLOW_UNAUTH_LOCALHOST=1` or a real token, else kaos-agents refuses to start.
- `integration/test_chat_stream_live.py` — POSTs to our proxy stream route, consumes SSE, asserts a `text_delta` and a `turn_summary` arrive. Gated on `ANTHROPIC_API_KEY`. Runs against `anthropic:claude-haiku-4-5`.
- `integration/test_kaos_agents_passthrough.py` — verifies the kaos-agents-owned routes are mounted and reachable. Quick smoke; failure means create_app changed shape.

### Frontend (`vitest`)

- `event-handler.test.ts` — 15 event types + 7 `(subject, phase)` span combos = 22 dispatch cases, each asserts a non-empty render.
- `transcript.test.ts` — Markdown + JSON round-trip on a fixture.
- `streaming.test.ts` — drive `readSseStream` against a recorded SSE log.
- `routes/__test__/*.tsx` — render tests on each route via `@testing-library/react` + `happy-dom`.

### Smoke

`make doctor` — runs `pytest -m smoke && pnpm test -- --run --reporter dot`. Acceptance: green on a fresh clone with `make sync-ui` first.

## 11. Security notes

- Bearer auth via kaos-agents' built-in. `compare_digest`-equivalent enforced inside kaos-agents (not our code).
- HTTPS via Caddy. `Caddyfile` lifted from `web:spa` and confirmed to carry CSP, X-Frame-Options=DENY, X-Content-Type-Options=nosniff, Referrer-Policy, Permissions-Policy, and `flush_interval -1` for SSE. **HSTS is provisioned but commented out** in the template — production deploys must uncomment it (line 24 of template `Caddyfile`).
- CORS: explicit dev origin only via `KAOS_AGENTS_API_CORS_ALLOW_ORIGINS`. Production must override.
- No `dangerouslySetInnerHTML`. Markdown rendered with `markdown-it` and a strict link sanitizer (`http(s)` and `mailto` only).
- Tool runtime defaults to `("kaos-core-*",)` — no write tools, no shell access. Toggle exposes read-only KAOS document tools only.
- Per-turn USD budget cap → `BudgetExceeded` event.

## 12. Open architectural questions

- **OAQ-1.** ~~Does kaos-agents' `POST /v1/sessions/{id}/messages` accept per-turn `model` / `instructions` / `tools` body fields?~~ **Resolved 2026-05-14: YES.** `MessageRequest` accepts `model`, `instructions`, `pattern`, `tools`, `max_cost_usd`, `require_approval_for_tools`. Our proxy HTTP-forwards with metadata applied. See `PATTERNS.md` P-005.
- **OAQ-2.** ~~Does kaos-agents' `POST /v1/sessions` accept arbitrary metadata fields?~~ **Resolved 2026-05-14: NO.** Only `session_id` is honored; extras are silently dropped. Our metadata sidecar is the source of truth. See `PATTERNS.md` P-003.
- **OAQ-3.** What does `kaos-agents` do if our proxy route bumps a session's metadata while the previous turn is still streaming? Probably fine because each turn's `MessageRequest` is processed standalone — kaos-agents doesn't cache the metadata between turns. Document the behavior once we observe it under concurrent send + patch.
- **OAQ-4.** Do we need an explicit `OPTIONS` route for the SPA's preflight on our extension router, or does kaos-agents' CORS middleware cover it? Verify in Phase 2 when the SPA actually makes cross-origin requests (in the dev proxy it's same-origin and CORS doesn't fire).
- **OAQ-5.** `HttpOnly` cookie auth would be ideal for the SPA. Does `create_app()` allow injecting a custom auth dependency to flip-flop between bearer and cookie? Phase 4 polish task. The cleaner workaround is to wrap the kaos-agents API behind our own auth middleware at the example level and use bearer locally.
