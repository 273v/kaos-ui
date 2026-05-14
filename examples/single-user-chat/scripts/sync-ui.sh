#!/usr/bin/env bash
# Stamps packages/ui from kaos_ui/templates/web/spa/packages/ui with placeholders rendered.
#
# packages/ui is regenerated on every `make install`. Do NOT hand-edit it.
# To change a shared component, edit the upstream template at
# kaos_ui/templates/web/spa/packages/ui/ and re-run `make sync-ui`.
#
# See docs/ARCHITECTURE.md § 2 for the rationale.

set -euo pipefail

# These three values match the slugs documented in docs/ARCHITECTURE.md.
NPM_SLUG="kaos-chat-example"
PROJECT_NAME="Single-User Chat"
PROJECT_SLUG="single-user-chat"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/../../kaos_ui/templates/web/spa/packages/ui"
DST="$ROOT/packages/ui"

if [[ ! -d "$SRC" ]]; then
  echo "error: template source not found at $SRC" >&2
  echo "       are you sure this is checked out inside kaos-modules?" >&2
  exit 1
fi

echo "sync-ui: wiping $DST"
rm -rf "$DST"

echo "sync-ui: copying $SRC → $DST"
mkdir -p "$(dirname "$DST")"
cp -r "$SRC" "$DST"

echo "sync-ui: rendering placeholders"
# GNU sed in-place. -E for extended regex. We only touch text files.
find "$DST" -type f \( \
    -name '*.ts' -o -name '*.tsx' -o -name '*.css' -o \
    -name '*.json' -o -name '*.md' -o -name '*.html' \
  \) -exec sed -i \
    -e "s/{{KAOS_NPM_SLUG}}/$NPM_SLUG/g" \
    -e "s/{{KAOS_PROJECT_NAME}}/$PROJECT_NAME/g" \
    -e "s/{{KAOS_PROJECT_SLUG}}/$PROJECT_SLUG/g" \
    {} +

# Sanity: verify no placeholders remain.
if remaining=$(grep -rE '\{\{KAOS_[A-Z_]+\}\}' "$DST" 2>/dev/null); then
  echo "sync-ui: ERROR — unrendered placeholders remain:" >&2
  echo "$remaining" >&2
  exit 2
fi

# Prune: upstream packages/ui ships sample-app stubs (`lib/api.ts` +
# `hooks/use-documents.ts` + `types/document.ts`) wired against a
# legacy /api/v1 + DocumentService that we don't consume. Their
# `import.meta.env` reference also breaks `tsc --noEmit` because
# packages/ui's tsconfig doesn't declare vite/client types and the
# package itself doesn't depend on vite. See docs/PATTERNS.md P-010.
# We use `apps/spa/src/lib/api-fetch.ts` instead.
rm -f "$DST/src/lib/api.ts" \
      "$DST/src/hooks/use-documents.ts" \
      "$DST/src/types/document.ts"
# Remove now-empty stub directories to keep the tree clean.
rmdir "$DST/src/types" 2>/dev/null || true
# Leave src/hooks and src/lib in place — they may host other content.

echo "sync-ui: ok ($DST is ready)"
