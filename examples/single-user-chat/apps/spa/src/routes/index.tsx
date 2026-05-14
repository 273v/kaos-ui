// Phase 0 probe — confirms the toolchain (vite + tailwind v4 + biome + tsc
// + TanStack Router) resolves the workspace UI package and renders.
// Phase 2 replaces this with the redirect-to-/sessions per the PLAN.

import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: Phase0Probe,
});

function Phase0Probe() {
  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center font-sans">
      <div className="text-center">
        <h1 className="text-4xl font-serif font-light mb-2">Single-User Chat</h1>
        <p className="text-sm text-muted-foreground">
          Phase 0 skeleton — toolchain OK. Phase 2 brings the real UI.
        </p>
      </div>
    </div>
  );
}
