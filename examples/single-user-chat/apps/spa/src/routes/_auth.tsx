// Auth gate — every route under `_auth/` requires a valid bearer.
//
// `beforeLoad` runs synchronously before React mounts the route. We
// check the auth context's ref-backed `isAuthenticated`; if false, we
// `refresh()` once (probes the bearer in localStorage against
// /v1/models) and only redirect on the boolean result.

import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_auth")({
  beforeLoad: async ({ context, location }) => {
    if (context.auth.isAuthenticated) return;
    const ok = await context.auth.refresh();
    if (!ok) {
      throw redirect({
        to: "/login",
        search: { redirect: location.href },
      });
    }
  },
  component: () => <Outlet />,
});
