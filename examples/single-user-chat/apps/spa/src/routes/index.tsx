// Root path → /sessions (the chat home).

import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/sessions", replace: true });
  },
});
