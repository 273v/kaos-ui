import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

/**
 * Pathless auth-gate layout. Every route under ``_auth`` is protected.
 *
 * The ``beforeLoad`` runs before the route component renders; if the
 * user isn't authenticated we throw ``redirect`` which TanStack Router
 * catches and navigates to ``/login`` instead.
 *
 * The layout is intentionally bare (``min-h-screen`` + Outlet only).
 * Each protected page owns its own padding, scroll container, and any
 * sticky chrome (e.g. the chat composer is bottom-pinned by the chat
 * route itself, not by this layout).
 *
 * Add new protected routes as ``src/routes/_auth.<name>.tsx``.
 */

export const Route = createFileRoute("/_auth")({
  beforeLoad: async ({ context, location }) => {
    if (context.auth.isAuthenticated) return;
    // One-shot /v1/auth/me probe — the cookie may still be valid
    // (page reload, fresh tab, or freshly-set after login()). Read the
    // boolean return directly: React state updates from setAuthed are
    // async and aren't visible on the same microtask tick.
    const ok = await context.auth.refresh();
    if (!ok) {
      throw redirect({
        to: "/login",
        search: { redirect: location.href },
      });
    }
  },
  component: () => (
    <div className="min-h-screen bg-background">
      <Outlet />
    </div>
  ),
});
