# Releasing

Two artifacts ship from this repo, each on its own tag:

| Artifact | Tag pattern | Registry | Workflow job |
|---|---|---|---|
| `kaos-ui` (Python scaffolder) | `v<version>` (e.g. `v0.1.0a15`) | PyPI | `publish-pypi` |
| `@273v/kaos-ui-react` (npm lib) | `kaos-ui-react@<version>` | npm | `publish-kaos-ui-react` |

Both are in `.github/workflows/release.yml`, triggered on tag push. Each
job verifies the in-repo version matches the tag before publishing.

## Python (`kaos-ui` → PyPI)

1. Bump `kaos_ui/_version.py`, finalize `CHANGELOG.md`.
2. Merge to `main`.
3. Tag + push: `git tag -a v<version> -m "…" && git push origin v<version>`.
4. CI verifies `__version__ == tag`, runs QA, publishes via PyPI Trusted
   Publishing (configured for this repo — works today).

## npm (`@273v/kaos-ui-react`)

> **Read this before the next npm release.** OIDC Trusted Publishing is
> **not currently configured on npmjs.org** for this package, so a tagged
> CI publish **404s silently** — this is how `0.1.0-alpha.10` and
> `0.1.0-alpha.11` were lost (the job looked done; nothing landed). The
> release workflow now **fails loudly** on this via a post-publish
> "Verify the version is actually live on npm" step, but the publish
> itself still needs ONE of the two auth paths below set up.

### Path A — automation token (recommended; reliable today)

1. On npmjs.com → **Access Tokens** → create a **Granular Access Token**
   (or Automation token) scoped to `@273v/kaos-ui-react` with
   **publish** permission. Prefer a short expiry + the narrowest scope.
2. Add it as a repository (or org) secret named **`NPM_TOKEN`**.
3. Release: bump `packages/kaos-ui-react/package.json` version, merge,
   then `git tag -a kaos-ui-react@<version> -m "…" && git push origin <tag>`.
4. CI authenticates with `NPM_TOKEN`, publishes with `--provenance`, and
   the verify step confirms the version is live (hard-fails if not).

### Path B — Trusted Publishing (tokenless OIDC)

1. On npmjs.com → the package → **Settings → Trusted Publishers** → add
   a GitHub Actions publisher: org `273v`, repo `kaos-ui`, workflow
   `release.yml` (and the environment if you scope one).
2. Leave `NPM_TOKEN` unset. CI publishes via OIDC + provenance.
   - Caveat: `actions/setup-node` with `registry-url` writes an `.npmrc`
     that expects `NODE_AUTH_TOKEN`; with no token that line is empty.
     If OIDC publish 404s, this is the usual cause — prefer Path A, or
     adjust the npm auth setup so no empty `_authToken` is written.

### Dist-tags

The publish step derives the dist-tag from the version string:
`*alpha*` → `alpha`, `*beta*` → `beta`, `*rc*` → `rc`, else `latest`.
The package is pre-1.0 alpha-only; consumers should install `@alpha`.
`latest` currently points at the stale `0.1.0-alpha.0` — once a stable
(non-prerelease) version ships it will move; until then, retagging
`latest` is a manual `npm dist-tag add @273v/kaos-ui-react@<ver> latest`.

### Manual fallback (when CI can't publish and a release is needed now)

If neither path is set up and the package must ship (e.g. an interactive
2FA account), publish from a trusted machine:

```bash
cd packages/kaos-ui-react
pnpm install --frozen-lockfile && pnpm run build
npm publish --dry-run --access public --tag alpha   # inspect first
npm publish --access public --tag alpha             # prompts 2FA
npm view @273v/kaos-ui-react dist-tags              # verify
```
