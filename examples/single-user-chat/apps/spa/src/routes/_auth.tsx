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

  // LOW #2 — Cmd/Ctrl-K opens a new chat. Pre-fix the docs advertised
  // this shortcut but no handler existed. Bound here so it works under
  // any authenticated route (sidebar visible or not).
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        // Skip when the user is typing in an editable field (Cmd-K is
        // also a browser-level shortcut; we don't want to hijack
        // search-bar interactions or the composer's send chord).
        const target = e.target as HTMLElement | null;
        const tag = target?.tagName?.toLowerCase() ?? "";
        if (tag === "input" || tag === "textarea" || target?.isContentEditable) return;
        e.preventDefault();
        if (createSession.isPending) return;
        const meta = await createSession.mutateAsync({});
        navigate({ to: "/sessions/$id", params: { id: meta.id } });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [createSession, navigate]);

  return <Outlet />;
}
