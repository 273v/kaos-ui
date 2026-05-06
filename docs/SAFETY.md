# kaos-ui Safe-by-Default Contract

> **Status:** Phase 0 stub. Phase 3 finishes this doc.

Every template `kaos-ui` ships satisfies the contract below at the moment of scaffold. If a template fails any of these, it is broken — not a feature gap.

## Identity

Every template ships with:

- A `Makefile` exposing the same verbs across kinds: `install`, `dev`, `test`, `up`, `down`, `doctor`, `bundle` (where applicable).
- A `CLAUDE.md` and `AGENTS.md` documenting agent guardrails for editing inside the scaffold.
- A `README.md` documenting the human-facing usage.
- A `.env.example` enumerating every secret the app reads.
- A `.gitignore` covering `.env`, `.env.local`, build outputs, OS junk, lockfile-adjacent artifacts.
- A `pre-commit-config.yaml` running formatters, linters, and a secrets scan.
- A `tests/` directory with at least one smoke test.

## Secrets

- Never baked into Dockerfiles.
- Never logged. Loaders use pydantic `SecretStr`.
- Loader refuses to start if `.env` is missing in any non-test environment.
- `gitleaks` runs as a pre-commit hook.

## Network

- Default bind is `127.0.0.1`. Public binding requires explicit `--host 0.0.0.0`.
- CORS allowlist is explicit; never `*`.
- Web templates ship a strict CSP: no `unsafe-inline`, no `unsafe-eval`.
- Cookies are `HttpOnly` + `SameSite=Lax`; `Secure` is set when `ENV=production`.
- TLS termination via Caddy with autocert by default in compose.

## Container

- Multi-stage build.
- Non-root user (`uid=1000`) in the runtime stage.
- Slim base (`python:3.14-slim` or `node:24-slim` or distroless where applicable).
- `HEALTHCHECK` directive present.
- Build args version-pin every base image.
- No secrets baked in.

## Configuration

- All config goes through pydantic-settings with `env_prefix`.
- Production deploys refuse to load with `DEBUG=True` when `ENV=production`.
- No `print()` in app code; everything routes through structured logging.

## Tests

- `make test` runs after `make install` on a fresh scaffold and exits 0.
- `make doctor` runs after `make install` on a fresh scaffold and exits 0.
- A smoke test proves the app actually boots.
