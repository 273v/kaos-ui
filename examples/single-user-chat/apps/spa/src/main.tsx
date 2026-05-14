// Phase 0 bootstrap — TanStack Router + Tailwind v4 + workspace UI fonts.
// Phase 2 (PLAN.md § 2.1) adds the QueryClient + AuthProvider + the
// real auth-context wrapper documented in templates/web/spa/src/main.tsx.

import "@kaos-chat-example/ui/fonts";
import "@/styles/globals.css";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { routeTree } from "./routeTree.gen";

const router = createRouter({
  routeTree,
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("missing #root in index.html");
}
createRoot(rootElement).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
