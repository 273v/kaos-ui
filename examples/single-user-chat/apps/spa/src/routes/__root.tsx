// Root route. Owns the router context type and renders a bare <Outlet/>.
// The AppShell wraps protected routes via `_auth.tsx`.

import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

import type { AuthContextValue } from "@/auth/context";

export interface RouterContext {
  auth: AuthContextValue;
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
});
