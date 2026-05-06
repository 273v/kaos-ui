# {{KAOS_PROJECT_NAME}} — Cross-tool Agent Notes

`CLAUDE.md` is the full runbook. This file is the one-page orientation
for any agent walking in cold.

## Two-minute orientation

1. **Read `CLAUDE.md`** for the full runbook (never-edit list, worked
   examples, troubleshooting, production checklist, OIDC swap path).
2. **Run `make doctor`.** Read its output before editing.
3. **Project shape:**
   - `backend/app/{main,settings,runtime,auth,deps,exceptions,logging_setup}.py`
   - `backend/app/routers/{health,auth,sessions,documents,search,uploads}.py`
   - `backend/app/services/{chat,documents,search,uploads}.py`
   - `apps/spa/src/{main.tsx, auth/, lib/, routes/}` — Vite + React
   - `packages/ui/` — shared shadcn primitives + utils
   - `Caddyfile`, `docker-compose.yml`, `Makefile` at the root
4. **Make the smallest change that solves the task.**
5. **Run `make test` AND `make typecheck` before declaring done.**

## Rules of thumb

- Routes stay thin; logic lives in `backend/app/services/*`.
- Heavy KAOS imports are lazy (inside service function bodies).
- `apiFetch` / `apiJson` are the only ways to talk to `/v1/*` from the
  SPA. Biome bans raw `fetch`.
- TanStack Router file-based — protected pages live under `_auth.*`.
  Public pages at `src/routes/` root.
- Never edit `routeTree.gen.ts` or files under `src/api/client/` —
  they're regenerated.
