// `/sessions` index — the empty-state landing when no session is selected.

import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_auth/sessions/")({
  component: SessionsEmpty,
});

function SessionsEmpty() {
  return (
    <div className="min-h-full flex items-center justify-center">
      <div className="text-center max-w-md px-8">
        <h1 className="text-4xl font-serif font-light mb-2">Welcome.</h1>
        <p className="text-sm text-muted-foreground">
          Start a conversation from the sidebar, or press <kbd>⌘K</kbd> for a new chat.
        </p>
      </div>
    </div>
  );
}
