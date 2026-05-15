# Release runbook — drop local-source overrides

Closes FIX-18. The local-source override block in
`examples/single-user-chat/backend/pyproject.toml` exists because four
upstream KAOS packages haven't yet shipped the fixes that landed during
the tool-policy + schema-fix work. This document is the per-package
plan to cut those releases so the override can be deleted and the
example consumes PyPI again.

**Status (2026-05-15):** CHANGELOG entries are landed on every
affected repo; per-repo dry-run release QA gates all pass. What
remains is a `_version.py` bump per repo + a tag push (CI publishes
on tag).

## Per-repo release plan

| Repo | Current | Target | Source-of-truth file | CI dry-run |
|---|---|---|---|---|
| kaos-core | 0.1.0a6 | **0.1.0a7** | `kaos_core/_version.py` | 562 passed |
| kaos-pdf | 0.1.0a2 | **0.1.0a3** | `kaos_pdf/_version.py` | 352 passed |
| kaos-office | 0.1.0a2 | **0.1.0a3** | `kaos_office/_version.py` | 498 unit passed |
| kaos-content | 0.1.0a6 | **0.1.0a7** | `kaos_content/_version.py` | 2461 passed |
| kaos-source | 0.1.0a3 | **0.1.0a4** | `kaos_source/_version.py` | 413 passed |
| kaos-tabular | 0.1.0a1 | **0.1.0a2** | `kaos_tabular/_version.py` | 314 passed |
| kaos-graph | 0.1.0-alpha.3 | **0.1.0-alpha.4** | `Cargo.toml [package].version` | 419 passed |
| kaos-agents | 0.1.0a1 | **0.1.0a2** | `kaos_agents/_version.py` | 2369 passed |

## Per-repo procedure (one PR per repo)

For each repo, the steps are identical (modulo path/branch names):

```bash
# 1. Branch from main and bump version + finalize CHANGELOG header
cd ~/projects/273v/kaos-core
git checkout -b release/0.1.0a7
sed -i 's/__version__ = "0.1.0a6"/__version__ = "0.1.0a7"/' kaos_core/_version.py
# Edit CHANGELOG.md: replace "## [Unreleased]" with
# "## [Unreleased]\n\n## [0.1.0a7] — YYYY-MM-DD"

# 2. Verify locally
uv run ruff format --check kaos_core tests
uv run ruff check kaos_core tests
uv run ty check kaos_core tests
uv run pytest -m "not live and not network and not slow" --no-cov
uv build
uvx --from twine twine check --strict dist/*

# 3. Commit + push + open PR
git commit -s -am "chore(release): 0.1.0a7"
git push origin release/0.1.0a7
gh pr create --fill --base main

# 4. After PR merges, tag + push (release.yml fires on tag push)
git checkout main && git pull
git tag v0.1.0a7
git push origin v0.1.0a7

# 5. Watch release.yml succeed
gh run watch
```

For **kaos-graph** the version source-of-truth is
`Cargo.toml [package].version = "0.1.0-alpha.4"` (Python imports the
version dynamically from Cargo per `docs/oss/30-rust-packaging/`).

## Coordinated release order

The dep chain matters:

1. **kaos-core 0.1.0a7** FIRST — every other package depends on it.
2. **kaos-pdf / kaos-office / kaos-content / kaos-source / kaos-tabular /
   kaos-graph** in any order — peer packages, no inter-dep on these
   changes.
3. **kaos-agents 0.1.0a2** LAST — depends on kaos-core 0.1.0a7's
   `items: {}` floor being on PyPI for the ReAct retry to compose
   correctly.

## After every package is on PyPI

In `kaos-ui/examples/single-user-chat/backend/pyproject.toml`:

```toml
# Bump the floors
"kaos-core>=0.1.0a7,<0.2",
"kaos-pdf>=0.1.0a3,<0.2",
"kaos-agents>=0.1.0a2,<0.2",
# (kaos-ui is already linked from local — that's the next release)

# Delete the [tool.uv.sources] block entirely
```

Then:

```bash
cd examples/single-user-chat/backend
uv lock
cd ../../..
git commit -s -am "chore(example): consume FIX-14..16 + TR-* from PyPI"
```

Smoke-test: run the example against PyPI-only deps and reproduce the
TR-11 live tests (`pytest tests/integration/test_tool_policy_live.py -m live`).

## Pre-flight verified (2026-05-15)

Every repo's `release.yml` pre-publish QA gate passes on the current
HEAD commit. Detailed scope per repo's release.yml:

- `kaos-core` / `kaos-content` / `kaos-tabular` / `kaos-graph` /
  `kaos-agents`: full `pytest -m "not live and not network and not slow"`.
- `kaos-office`: `pytest tests/unit/` only (integration tests need
  `kaos_mcp` extra; gated behind it).
- `kaos-source`: `pytest -m "not live and not network and not slow and
  not integration"` (matches ci.yml per F011 marker contract).
- `kaos-pdf`: full `pytest -m "not live and not network and not slow"`.

All produced clean wheels + sdists; `twine check --strict` PASSED on
every dist.

## kaos-ui itself

kaos-ui ships TR-1 (`register_kaos_tool_groups`) + P1-5
(`kaos_ui.uploads`) + the new exception types — those land in
kaos-ui 0.1.0a2. Procedure mirrors the others; CHANGELOG entry
is already in place under `[Unreleased]`.
