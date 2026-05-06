# kaos-ui Deployment Guide

> How to actually ship a scaffolded project — local-dev, internal
> intranet, public-facing — and what's verified end-to-end vs. what
> still needs the user's hands.

## Status of each path

| Deploy path | Streamlit | Textual | Web SPA |
|---|---|---|---|
| `make dev` (local-dev) | ✅ live-verified (curl + Playwright screenshot) | ✅ live-verified (smoke via `App.run_test()`) | ✅ live-verified (curl auth flow + Playwright login → chat) |
| `pipx install` / `uv tool install` | n/a | ✅ wheel build verified | n/a |
| `docker compose up` | ⚠️ blocked: see "PyPI gap" below | n/a (TUIs not compose'd) | ⚠️ blocked: see "PyPI gap" below |
| Behind Caddy with TLS | ⚠️ Caddyfile shipped but not yet tested with real cert | n/a | ⚠️ Caddyfile shipped but not yet tested with real cert |

**"Verified" = a fresh scaffold installed cleanly, the server booted, real network calls (curl / Playwright) confirmed the auth + happy-path flows.**

## The PyPI gap

`kaos-core` is the only KAOS package on PyPI today. `kaos-agents`,
`kaos-content`, `kaos-pdf`, `kaos-office`, `kaos-llm-client` etc. are
not yet published.

Every template's `pyproject.toml` references these packages with
PyPI-shaped version pins (`kaos-agents>=0.1.0`). On a machine that
isn't running inside the kaos-modules workspace, `uv sync` fails:

```
× Because kaos-agents was not found in the package registry and your
  project depends on kaos-agents>=0.1.0, we can conclude that your
  project's requirements are unsatisfiable.
```

This blocks `docker compose up` end-to-end deployment for any
template that depends on `kaos-agents` or other unpublished
extras — which is all three Phase 1 templates.

### Workaround for local-dev (today)

If you scaffolded inside the kaos-modules workspace, append
`[tool.uv.sources]` overrides to the relevant `pyproject.toml`. Each
template's `CLAUDE.md` documents the exact stanza. Example
(`web:spa` backend):

```toml
[tool.uv.sources]
kaos-core      = { path = "../../kaos-core",      editable = true }
kaos-content   = { path = "../../kaos-content",   editable = true }
kaos-agents    = { path = "../../kaos-agents",    editable = true }
kaos-llm-client = { path = "../../kaos-llm-client", editable = true }
kaos-pdf       = { path = "../../kaos-pdf",       editable = true }
kaos-office    = { path = "../../kaos-office",    editable = true }
```

Inside the workspace, `make install` + `make dev` work end-to-end
today. The kaos-ui integration tests do exactly this (with a stripped
minimal-deps `pyproject` for speed).

### Path forward

Publish the kaos-* packages to PyPI. The Dockerfiles (multi-stage
non-root with libmagic + healthcheck) build cleanly when the deps
resolve from PyPI — verified by building the SPA backend Dockerfile
against a stripped pyproject (kaos-core omitted, all other deps from
PyPI; image built and uvicorn started).

## Local-dev: `make dev`

Each template's `make dev`:

| Template | What runs |
|---|---|
| Streamlit | `uv run streamlit run app.py` on `:8501` (single process) |
| Textual | `uv run python -m {slug}` (full-screen TUI in current terminal) |
| Web SPA | `uvicorn` on `:8000` + `vite dev` on `:5173`, in parallel via `make`'s job control |

For all three, before first run:

```bash
cp .env.example .env       # set APP_AUTH_TOKEN + your LLM API key
make install               # uv sync (+ pnpm install for SPA)
make doctor                # exits 0 on a fresh scaffold
make dev
```

`make doctor` is the deploy-readiness gate. Running it should be the
first thing an agent does after editing.

## Distribution: `pipx install` / `uv tool install`

For the Textual TUI template specifically, distribution is simple:

```bash
make build                       # produces dist/*.whl
pipx install dist/*.whl          # binary on PATH
{slug}                           # run it
```

`pyproject.toml` declares
`[project.scripts] {slug} = "{module}.app:run"`. The script calls
`{Slug}App().run()`.

## Behind Caddy: `docker compose up`

Streamlit and Web SPA both ship a `Caddyfile` and `docker-compose.yml`:

```bash
docker compose up -d --build
```

What this does (web:spa):

- Builds the backend image (multi-stage uv → non-root distroless-ish slim).
- Builds the frontend with `vite build` (mounted as static assets at `/srv` for Caddy).
- Starts the backend container on `:8000` (internal network only).
- Starts Caddy bound to `127.0.0.1:8080` and `127.0.0.1:8443` (loopback
  by default — public exposure is opt-in).
- Caddy:
  - Terminates TLS (auto-certs via Let's Encrypt when `Caddyfile` is
    edited to use a real domain instead of `localhost`).
  - Forwards `/v1/*` to the backend with `flush_interval -1` for SSE.
  - Serves the SPA static build for everything else.
  - Injects security headers (CSP, HSTS, X-Frame-Options,
    Permissions-Policy, etc.).
  - Strips `Server` and `X-Powered-By` headers.

### Production checklist

Per the per-template `CLAUDE.md`:

- [ ] `APP_ENV=production`, `APP_DEBUG=false`
- [ ] `APP_AUTH_TOKEN` is random and ≥ 32 chars
- [ ] `APP_CORS_ORIGINS` is the explicit prod origin (no `*`, no localhost)
- [ ] LLM API key set for `APP_LLM_PROVIDER`
- [ ] `Caddyfile`: replace `localhost` with the real domain (auto-TLS)
- [ ] If exposing publicly, change compose binds from `127.0.0.1:8443`
      to `0.0.0.0:443`
- [ ] `make doctor` exits 0
- [ ] `make test` passes
- [ ] (Recommended) `gitleaks detect --source .` clean
- [ ] (Recommended) `trivy image {slug}-backend:latest` no high/critical

The `Caddyfile` ships with HSTS commented out. Uncomment after you
verify TLS works on the real domain — HSTS is a one-way switch
(browsers cache it; a misconfigured cert leaves users locked out for
the `max-age` period).

### Postgres overlay

The default state path is SQLite inside `.kaos-vfs/`. For production
multi-instance deploys, use the postgres overlay:

```bash
export POSTGRES_PASSWORD=$(openssl rand -hex 32)
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d
```

Set `APP_DATABASE_URL=postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@postgres:5432/{slug}` in `.env`.

## Auth: bearer-from-`.env` is local-only

The default token-from-`.env` auth is suitable for:

- Single-user / single-team internal dashboard.
- Behind a VPN or a reverse proxy with its own auth.
- Localhost dev.

It is **not** suitable for public-internet deploys without an upstream
auth layer. Per the template `CLAUDE.md`:

- Streamlit: replace `auth.require()` body with `st.login()` (OIDC,
  Streamlit ≥1.42).
- Web SPA: replace the `/v1/auth/login` body with an OIDC code-flow
  handler — the cookie shape is the contract; the issuer is
  swappable.
- Alternative for both: front Caddy with `oauth2-proxy` and trust
  `X-Forwarded-Email` server-side.

## Observability: where logs go

| Template | Logs go to |
|---|---|
| Streamlit | stderr — Streamlit captures and streams via `streamlit run` |
| Textual | `~/.kaos/{slug}/log.jsonl` (rotating, JSON). Textual owns the terminal so console logs would corrupt the UI |
| Web SPA | stderr in dev (human format), stderr in prod (JSON). `docker compose logs -f` in prod |

All KAOS module logs (anything under the `kaos.*` logger hierarchy)
flow through the same handler. CWE-117 CR/LF stripping is applied
at the formatter so an attacker who controls a logged value (an
upload's filename, a chat message) can't forge fake log lines.

## What still needs the user

For a hosted production deploy, the template sets the foundation but
the user (or their agent) needs to:

1. **Acquire a domain** + DNS A/AAAA records pointing at the host.
2. **Edit the `Caddyfile`** — replace `localhost` with the real
   domain. Caddy will auto-acquire a Let's Encrypt cert.
3. **Open ports 80 and 443** in the firewall (Caddy handles HTTP→HTTPS
   redirect).
4. **Switch compose binds** from `127.0.0.1:8443` to `0.0.0.0:443`.
5. **Provision a secret manager** (Doppler, Vault, AWS Secrets Manager,
   …) and replace `.env` reads with whatever the platform expects.
6. **Set up backups** for `.kaos-vfs/` (or the postgres volume).
7. **Wire monitoring** — health/ready probes are exposed at `/v1/health`
   and `/v1/ready` for the web:spa template.

## Live verification harness

The kaos-ui repo's `tests/integration/test_scaffold_*.py` cover:

- Cheap structural tests (dry-run, AST/compile/ruff on rendered Python).
- Heavy integration: scaffold + minimal-deps install + run the
  scaffolded project's deterministic Python tests.

What they do *not* cover (deferred to manual / live tier):

- Full kaos-* workspace install (PyPI gap).
- Vite build + Playwright e2e of the SPA frontend (heavy: 200+ npm
  packages on a cold cache).
- `docker build` end-to-end (PyPI gap).
- `docker compose up` against a real domain with TLS.

The session that built this template ran all four manually, captured
screenshots in `/tmp/live-screenshots/`, and committed the seven bug
fixes that surfaced — see `docs/PATTERNS.md` and the commit history
for the full list.
