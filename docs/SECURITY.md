# kaos-ui SECURITY

> The concrete security contract every kaos-ui template implements.
> More specific than `SAFETY.md` (which is a developer-facing summary).
> Maps to OWASP Top 10:2025 and OWASP Top 10 for LLM Applications 2025.

## Threat model

The vibe coder is a non-developer driving an LLM agent. They will:

- Run `kaos-ui new` and accept whatever the agent edits.
- Deploy to public-facing infrastructure (Fly, Railway, a VPS).
- NOT review the generated code carefully.
- NOT run `bandit` or `trivy` themselves unless the template makes it
  trivial.

The agent will:

- Edit code based on user requests, occasionally introducing footguns.
- Not always question prompt-injection attempts coming through tool
  outputs.
- Run with broad VFS / network access by default unless the template
  enforces narrower scopes.

The template's job is to make the secure path the easy path, and to
**fail loud** when the user is about to do something insecure rather
than silently degrading.

## What every template ships with

| Mitigation | Where | OWASP map |
|---|---|---|
| Refuse-to-start in production with weak/missing `APP_AUTH_TOKEN`, `APP_DEBUG=true`, weak token literals (`changeme`, `password`, etc.), tokens < 32 chars | `{slug}/settings.py` `_validate_security_invariants` | A05 Security Misconfig |
| `SecretStr` for every key/token; auto-redacted in logs and Settings page | `{slug}/settings.py`, `model_dump_redacted` walks all fields | A09 Logging Failures |
| Bearer-token auth gate with `hmac.compare_digest` (timing-safe) | `{slug}/auth.py` | A07 Identification + Auth |
| Test-env auth bypass requires explicit `APP_ENV=test` | `{slug}/auth.py:is_authenticated` | A05 |
| File upload: 25 MB cap + extension allowlist + magic-byte verification | `{slug}/services/uploads.py` | A04 Insecure Design (CWE-434) |
| Document IDs: sha256 hex (no path separators, no traversal) | `{slug}/services/uploads.py:_make_document_id` | A01 Broken Access Control |
| CWE-117 log injection: strip CR/LF in JSON formatter | `{slug}/logging_setup.py:_strip_crlf` | A09 |
| `.gitignore` covers `.env` + `secrets.toml` + build artifacts | `.gitignore` | A05 |
| Pre-commit gitleaks scan on every commit | `.pre-commit-config.yaml` | Software Supply Chain |
| pnpm 11.1+ pinned through `packageManager`; 72-hour registry cooldown; strict dependency build-script allowlist; exotic transitive dependency specs blocked | `package.json`, `pnpm-workspace.yaml`, `kaos-ui doctor` | Software Supply Chain |
| Multi-stage Dockerfile, non-root `uid=1000`, slim base, `HEALTHCHECK` | `Dockerfile` | A05 |
| Compose binds `127.0.0.1` only by default | `docker-compose.yml` | A05 |
| Bounded `@st.cache_resource(ttl=3600, max_entries=1)` to prevent OOM | `app.py` | A05 |
| Streamlit `showErrorDetails = "none"` (no traceback leak in prod) | `.streamlit/config.toml` | A09 |
| Streamlit `magicEnabled = false` (no bare-expression UI leak) | `.streamlit/config.toml` | A09 |
| Streamlit `enableCORS = true` + `enableXsrfProtection = true` | `.streamlit/config.toml` | A05 |

## What templates do NOT do (yet)

- **Distroless container** — current base is `python:3.14-slim` with
  `apt-get install curl` for healthcheck. Distroless would shrink the
  attack surface but breaks the `make doctor` `curl` healthcheck path.
  Phase 4 hardening.
- **`--read-only` rootfs** — not enabled. Compose users can add
  `read_only: true` themselves. Future template hardening.
- **`--cap-drop=ALL` / `--security-opt=no-new-privileges`** — not in
  the default compose. Future hardening.
- **Antimalware (ClamAV) on uploads** — not wired. Magic-byte
  verification is the current bar. ClamAV via sidecar is a Phase 4
  add.
- **Per-session LLM cost ceiling** — agents can in principle loop and
  burn budget. `kaos-agents` settings include `KAOS_AGENT_MAX_COST_USD`
  (per its CLI). Templates should expose a wrapper but currently rely
  on kaos-agents' own ceilings. Document in CLAUDE.md.
- **Egress allowlist on httpx** — agent tools that fetch URLs do not
  yet enforce a positive scheme + non-private-IP allowlist. SSRF risk
  if an agent is asked to fetch a user-supplied URL. Phase 4 — depends
  on kaos-web settings.
- **Real OIDC / OAuth** — bearer-from-`.env` is the default. The
  template's CLAUDE.md documents the swap path to Streamlit's
  `st.login()` (≥1.42) for OIDC, or to a Caddy `forward_auth` for
  reverse-proxy auth. Production deployments past a single team
  should make that swap.

## Refuse-to-start checklist (the template tests)

Every template's settings test suite includes these "refuse to load"
cases:

- [x] Missing `APP_AUTH_TOKEN` in dev/prod (test env exempt)
- [x] `APP_ENV=production` + `APP_DEBUG=true`
- [x] `APP_ENV=production` + token in `{changeme, password, admin, dev, test, secret, default}`
- [x] `APP_ENV=production` + token length < 32

Future:

- [ ] `APP_ENV=production` + `--server.address 0.0.0.0` without proxy
- [ ] Detect committed `.env` (presence in `git ls-files`) and refuse

## Node dependency supply-chain

Generated pnpm workspaces use a conservative default posture:

- `packageManager` pins `pnpm@11.1.0` so Corepack selects a toolchain
  with dependency cooldowns, build-script allowlists, exotic-subdep
  blocking, and `pnpm audit signatures`.
- `pnpm-workspace.yaml` sets `minimumReleaseAge: 4320` (72 hours) with
  non-strict fallback, missing-time tolerance, and `resolutionMode:
  highest` for registry compatibility, `blockExoticSubdeps: true`,
  `strictDepBuilds: true`, `dangerouslyAllowAllBuilds: false`, and
  `savePrefix: ""`.
- `allowBuilds` is explicit and small. New entries require review
  because install-time lifecycle scripts are a supply-chain boundary.
- The SPA template does not ship a static `pnpm-lock.yaml` because
  workspace package names are templated. `kaos-ui doctor` warns until
  the generated project runs `pnpm install` and commits its lockfile.
- CI should run `pnpm install --frozen-lockfile` and
  `pnpm audit signatures` after the first lockfile is committed.

## Required scanning (per kaos-ui release)

| Tool | Scope | When |
|---|---|---|
| `gitleaks` | Templates dir + repo history | pre-commit + CI |
| `ruff check --select=S` | Generated Python | per-PR (run inside scaffolded project) |
| `trivy image` | Built Docker image | per-release |
| `hadolint` | Every `Dockerfile` | per-PR |
| `bandit -r` | Generated Python (Phase 4) | per-PR |
| `pip-audit` / `uv pip audit` | Generated lockfile | per-PR |

The gate for a release is: all of the above clean, plus the existing
`ruff format / ruff check / ty check / pytest` for the kaos-ui repo
itself.

## Vibe-coder footguns the template makes hard

These are the things a non-developer agent-driven user is most likely
to break, and what the template does about each:

| Footgun | What the template does |
|---|---|
| Commit `.env` | `.gitignore` excludes it; pre-commit gitleaks scan blocks |
| Hardcode `BEARER_TOKEN="..."` from a tutorial | Settings refuse-to-start blocks weak literals in production |
| Run `streamlit run` bound to `0.0.0.0` without auth | Compose binds `127.0.0.1`; production swap requires explicit override |
| Upload a renamed `.exe` as `.pdf` | Magic-byte verification rejects mismatch |
| Paste a debug variable into a page and accidentally show it | `magicEnabled = false` requires explicit `st.write()` |
| Catch all exceptions and log `f"error: {user_input}"` | `_strip_crlf` defeats CWE-117 even if the developer forgets |
| Forget to set `ttl` on `@st.cache_resource` and OOM | Template ships with `ttl=3600, max_entries=1` and PATTERNS.md flags this |

## Sources

- [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
- [OWASP Top 10 for LLM Applications 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [CWE-117 Log Injection](https://cwe.mitre.org/data/definitions/117.html)
- [CWE-434 Unrestricted Upload of File with Dangerous Type](https://cwe.mitre.org/data/definitions/434.html)
- [Streamlit security overview](https://docs.snowflake.com/en/developer-guide/streamlit/object-management/security)
- [pydantic SecretStr docs](https://docs.pydantic.dev/latest/api/types/#pydantic.types.SecretStr)
