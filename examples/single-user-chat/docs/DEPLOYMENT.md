# single-user-chat — Deployment

> Status: draft. Last updated: 2026-05-14. This document covers the
> single-user, single-host deployment shape. Multi-user / multi-host
> deployments are explicitly out of scope (see `PRD.md` § 4 Non-goals).

## 1. What you're deploying

A two-container compose stack:

- **`backend`** — uvicorn serving `app.main:app`. The FastAPI app mounts
  `kaos_agents.api.server.create_app()` and layers our extension routers
  on top. Persistent state is `.kaos-vfs/` on disk; mount it as a volume.
- **`caddy`** — TLS terminator + SPA static-file server + reverse proxy
  for `/v1/*` to the backend.

Frontend is a pure static build (Vite). No SSR.

## 2. Pre-deployment checklist

- [ ] `APP_ENV=production` (refuses weak settings)
- [ ] `KAOS_AGENTS_API_API_TOKEN` is a random string ≥ 32 chars
      (production refuses shorter — see `PATTERNS.md` P-002).
      **Note the double-`API_` prefix** (`PATTERNS.md` P-001).
- [ ] `KAOS_AGENTS_API_API_CORS_ALLOW_ORIGINS` lists the explicit
      production origin only — never `*` with credentials.
- [ ] At least one LLM provider key set (matching `APP_DEFAULT_MODEL`'s
      provider prefix).
- [ ] `Caddyfile`: replace `localhost` with the real domain.
- [ ] HSTS uncommented in `Caddyfile` (it ships provisioned-but-commented;
      `PATTERNS.md` P-006). Only enable after TLS is verified working.
- [ ] `pnpm-lock.yaml` and `backend/uv.lock` committed; CI uses
      `make install-ci` for frozen installs.
- [ ] `make doctor` exits 0; `make test` passes (incl. the live LLM gate).
- [ ] `gitleaks` + `trivy` scans clean on the resulting tree.

## 3. Build

```bash
cd kaos-ui/examples/single-user-chat
make sync-ui                 # stamps packages/ui from the web:spa template
make install                 # uv sync + pnpm install
pnpm --filter "*spa" build   # produces apps/spa/dist
make build                   # docker compose build
```

## 4. Run (compose)

```bash
make up         # detached: caddy on 127.0.0.1:8443 → backend:8000
make doctor     # check health
# logs:
docker compose logs -f backend caddy
# stop:
make down
```

The compose stack binds Caddy to `127.0.0.1:8443` by default. For
public-internet exposure, swap to `0.0.0.0:443` AND enable HSTS AND
configure the real domain in `Caddyfile`.

## 5. Workspace overrides for development against kaos-modules

If you're developing this example **inside the `kaos-modules` monorepo**
(rather than off PyPI), and you want to test against your local
working copy of `kaos-agents` / `kaos-core` / etc., add to `backend/pyproject.toml`:

```toml
[tool.uv.sources]
kaos-core       = { path = "../../../kaos-core",       editable = true }
kaos-agents     = { path = "../../../kaos-agents",     editable = true }
kaos-llm-core   = { path = "../../../kaos-llm-core",   editable = true }
kaos-llm-client = { path = "../../../kaos-llm-client", editable = true }
kaos-content    = { path = "../../../kaos-content",    editable = true }
kaos-pdf        = { path = "../../../kaos-pdf",        editable = true }
kaos-office     = { path = "../../../kaos-office",     editable = true }
```

Then `uv sync` picks up the local source. **Do not commit these
overrides** to the example — they're a personal-workspace thing.

## 6. PyPI distribution

The example **is not** published to PyPI in v1. It lives in the
`kaos-modules` repo only. Users `git clone` and `make install`. See
`PRD.md` § 4 (Non-goals) for the rationale.

If we ever publish: add `/examples` to `[tool.hatch.build.targets.sdist]
include` in `kaos-ui/pyproject.toml`. Installed users find the example
at `site-packages/kaos_ui/examples/single-user-chat/`.

## 7. Backup + restore

Single artifact: `.kaos-vfs/`. Back this up to take everything
(metadata sidecar + kaos-agents memory + graph turtle).

```bash
# back up
tar czf kaos-vfs-$(date +%Y%m%d).tar.gz .kaos-vfs/

# restore
tar xzf kaos-vfs-20260514.tar.gz
```

No database, no Redis. Single-user simplicity.

## 8. Health monitoring

- `GET /v1/health` returns `{"status":"ok"}` and is what docker-compose
  uses for the container healthcheck (`backend/Dockerfile` HEALTHCHECK
  block uses urllib — no curl in the image).
- All backend logs go to stderr in JSON format when `APP_ENV=production`.
  Ship them to your preferred sink with the standard docker logging
  driver.

## 9. Cost guardrails

- Per-turn USD budget cap is set via `APP_TURN_BUDGET_USD` (default
  `0.50`). The agent emits a `BudgetExceeded` event if a turn would
  exceed this — the frontend banner says so and truncates the message.
- The model catalog is curated; users can only switch among the IDs in
  `backend/app/services/catalog.py`. Add new models to the catalog
  intentionally (and re-verify against `kaos_llm_client.cost.MODEL_PRICING`).

## 10. What still needs the user

This example is **not** a turnkey product. After the deployment
checklist above, the user still needs to:

- Pick a hostname + DNS record for production
- Provision a TLS certificate (Caddy can do this automatically with
  Let's Encrypt — set the `email` directive in the global config block)
- Set up backups + monitoring per their infrastructure conventions
- Decide whether to enable any optional KAOS tools (PDF, Office, etc.)

The example proves the wire pipeline works end-to-end against the
kaos-agents-bundled FastAPI app. Productionizing it is the user's job.
