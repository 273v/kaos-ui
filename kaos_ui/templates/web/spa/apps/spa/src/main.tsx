// Self-hosted fonts (Inter + Source Serif 4) — no Google Fonts CDN.
// The actual fontsource imports live in the shared UI package so deps
// and imports stay co-located. Order matters: fonts before globals.css.
import "@{{KAOS_NPM_SLUG}}/ui/fonts";
import "@/styles/globals.css";
// @273v/kaos-ui-react theme tokens + JSON-tree + markdown styles.
// Load AFTER globals.css so consumer overrides win on the cascade.
import "@273v/kaos-ui-react/styles.css";
import { KaosUIProvider, type Transport } from "@273v/kaos-ui-react/lib";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { type AuthContextValue, AuthProvider, useAuth } from "@/auth/context";
import { routeTree } from "./routeTree.gen";

// Backend coordinates for every @273v/kaos-ui-react hook + component.
// baseUrl points at the API; same-origin in dev (Vite proxy) and prod
// (Caddy fronting backend). `getToken` returns null because the
// kaos-ui template ships with httpOnly-cookie auth — apiFetch sets
// `credentials: "include"` so the cookie attaches automatically.
const transport: Transport = {
  baseUrl: "/v1",
  getToken: () => null,
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Don't auto-refetch on window focus — agent-edited dashboards
      // typically have low data churn and high attention switching.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

// Placeholder auth context for the router's static context. The real
// AuthContextValue is injected via the RouterProvider `context` prop
// at render time (see RouterProviderWithAuth), so this default is
// never consumed in practice — but TanStack Router needs SOMETHING
// here, and a typed no-op beats a non-null assertion.
const placeholderAuth: AuthContextValue = {
  isAuthenticated: false,
  login: async () => false,
  logout: async () => {},
  refresh: async () => false,
};

const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  context: {
    auth: placeholderAuth,
    queryClient,
  },
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

function RouterProviderWithAuth() {
  const auth = useAuth();
  return <RouterProvider router={router} context={{ auth, queryClient }} />;
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("missing #root in index.html");
}
createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <KaosUIProvider transport={transport}>
        <AuthProvider>
          <RouterProviderWithAuth />
        </AuthProvider>
      </KaosUIProvider>
    </QueryClientProvider>
  </StrictMode>,
);
