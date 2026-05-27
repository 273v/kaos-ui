// Auth gate — every route under `_auth/` requires a valid bearer.
//
// `beforeLoad` runs synchronously before React mounts the route. We
// check the auth context's ref-backed `isAuthenticated`; if false, we
// `refresh()` once (probes the bearer in localStorage against
// /v1/models) and only redirect on the boolean result.

import { createFileRoute, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

import { useCreateSession } from "@/hooks/use-create-session";

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
  component: AuthedShell,
});

function AuthedShell() {
  const createSession = useCreateSession();
  const navigate = useNavigate();

  // Cmd/Ctrl-K opens a new chat. Bound here so it works under any
  // authenticated route (sidebar visible or not). Capture-phase + always
  // preventDefault so the shortcut works from inside the composer too —
  // the original "skip when focus is in an input" guard made the
  // advertised shortcut a no-op for the 99% of the time the user is
  // actually typing in the composer, and Chrome's default Cmd/Ctrl-K
  // (search-bar focus) was firing instead, which behaves like a page
  // refresh under some browser configs.
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        // Honour modifier keys that turn Cmd-K into something else
        // (Cmd-Shift-K is "show inspector" / "developer tools" in some
        // browsers — leave those alone).
        if (e.shiftKey || e.altKey) return;
        e.preventDefault();
        if (createSession.isPending) return;
        const meta = await createSession.mutateAsync({});
        navigate({ to: "/sessions/$id", params: { id: meta.id } });
      }
    };
    // capture: true so we win the race against any nested input handlers
    // (the composer textarea, sidebar search, etc.).
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [createSession, navigate]);

  return <Outlet />;
}
