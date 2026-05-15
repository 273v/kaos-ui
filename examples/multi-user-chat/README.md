# multi-user-chat

Second canonical example for `@273v/kaos-ui-react` (UI-I). Proves the
package generalizes beyond a single-user deploy by adding two pieces
the single-user example deliberately doesn't ship:

1. **Multi-tenant `SessionStore` namespace** — sessions live at
   `tenants/{user_id}/sessions/{session_id}/meta.json` instead of the
   flat `sessions/...` path. The same `kaos_ui.uploads` helpers work
   per-tenant because every helper takes the session id; the prefix
   is derived from `f"tenants/{tenant_id}/files/{filename}"`.
2. **JWT-based auth** — replaces the single shared bearer with HS256
   JWTs carrying a `sub` (user_id) claim. The auth dependency
   extracts the tenant id and scopes every SessionStore call to it.

What this example does NOT ship (followups, intentional):
- **OIDC code flow.** Production multi-user deploys typically front
  with an OIDC IdP (Auth0, Okta, Cognito, custom). The JWT shape
  here is intentionally simple so the substitution point is clear —
  swap the issuer in `app/auth.py` to point at your IdP's JWKS and
  the rest of the pipeline stays unchanged.
- **Presence indicators.** Who-else-is-in-this-session would need a
  WebSocket / Redis pub/sub channel; out of scope.
- **Optimistic concurrency on session edits.** Two-user same-session
  edits would need an ETag/If-Match dance on PATCH.
- **Shared documents tab.** A second user joining a session would
  need separate ACL data beyond the per-tenant prefix.

## What's identical to single-user-chat

- The chat surface — `@273v/kaos-ui-react` is the same package; the
  SPA shape is the same. Just plumbed against a different auth +
  storage prefix.
- Every TR-1..TR-13 feature: tool registry, SessionToolSet ceiling,
  per-turn TurnToolPolicy planner, ToolPolicyBadge transparency.
- The `kaos_ui.uploads` pipeline: store_and_parse, list/read/delete,
  render_session_corpus_markdown, backfill — all work as-is, just
  scoped per-tenant.

## What's different vs single-user-chat

| Concern | single-user | multi-user |
|---|---|---|
| Auth shape | one shared bearer token | per-user HS256 JWT |
| Session VFS prefix | `sessions/{id}/...` | `tenants/{user_id}/sessions/{id}/...` |
| `SessionStore.list()` | all sessions | filtered to `tenant_id` |
| Settings | `APP_AUTH_TOKEN` | `APP_JWT_SECRET` |

## Status

This example is **skeleton-only** as shipped — backend stubs +
docs + the multi-tenant abstraction layer. The SPA, Caddyfile, and
Docker compose haven't been built. Once the wire shapes are
validated by an integration test, copy them from single-user-chat
and adjust the auth fetch.
