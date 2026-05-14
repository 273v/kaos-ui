// Root route. Phase 0: just renders <Outlet/>. Phase 2 wraps it in the
// AppShell (sidebar + header) per docs/UX-LANGUAGE.md § 4.1.

import { Outlet, createRootRoute } from "@tanstack/react-router";

export const Route = createRootRoute({
  component: () => <Outlet />,
});
