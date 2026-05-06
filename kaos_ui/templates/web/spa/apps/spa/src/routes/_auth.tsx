import { Outlet, createFileRoute, redirect } from "@tanstack/react-router";

/**
 * Pathless auth-gate layout. Every route under ``_auth`` is protected.
 *
 * The ``beforeLoad`` runs before the route component renders; if the
 * user isn't authenticated we throw ``redirect`` which TanStack Router
 * catches and navigates to ``/login`` instead.
 *
 * Add new protected routes as ``src/routes/_auth.<name>.tsx``.
 */

export const Route = createFileRoute("/_auth")({
  beforeLoad: async ({ context, location }) => {
    if (!context.auth.isAuthenticated) {
      // Try a one-shot /v1/auth/me probe in case the cookie is still
      // valid (page reload, same browser session).
      await context.auth.refresh();
      if (!context.auth.isAuthenticated) {
        throw redirect({
          to: "/login",
          search: { redirect: location.href },
        });
      }
    }
  },
  component: () => (
    <div className="flex flex-col gap-4 p-6">
      <Outlet />
    </div>
  ),
});
