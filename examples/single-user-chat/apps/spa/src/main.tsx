// SPA entrypoint — TanStack Router + Query + bearer-token auth.
//
// The QueryClient + AuthContext are passed into the router's `context`
// so route-level `beforeLoad` guards and loaders can read them without
// going through React (they run before the React tree mounts).

import "@kaos-chat-example/ui/fonts";
import "@/styles/globals.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { type AuthContextValue, AuthProvider, useAuth } from "@/auth/context";
import { routeTree } from "./routeTree.gen";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // Don't retry 4xx — they're our fault (bad bearer, etc).
        if (typeof error === "object" && error && "status" in error) {
          const status = (error as { status: number }).status;
          if (status >= 400 && status < 500) return false;
        }
        return failureCount < 2;
      },
    },
  },
});

// Placeholder used only at router construction; replaced with real
// auth via `<RouterProviderWithAuth/>` below.
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
      <AuthProvider>
        <RouterProviderWithAuth />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
