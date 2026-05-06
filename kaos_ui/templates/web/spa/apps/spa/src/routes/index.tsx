import { createFileRoute, redirect } from "@tanstack/react-router";

// Landing route — sends authenticated users to chat, others to login.
export const Route = createFileRoute("/")({
  beforeLoad: ({ context }) => {
    if (context.auth.isAuthenticated) {
      throw redirect({ to: "/chat" });
    }
    throw redirect({ to: "/login" });
  },
});
