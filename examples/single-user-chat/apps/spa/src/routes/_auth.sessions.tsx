// Sessions shell — sidebar + Outlet. The list itself lives in the sidebar,
// and routes _auth.sessions.index (empty state) / _auth.sessions.$id (chat
// detail) render into the main column.

import { createFileRoute, Outlet } from "@tanstack/react-router";

import { Sidebar } from "@/components/layout/Sidebar";

export const Route = createFileRoute("/_auth/sessions")({
  component: SessionsLayout,
});

function SessionsLayout() {
  return (
    <div className="flex h-screen bg-background text-foreground font-sans">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
