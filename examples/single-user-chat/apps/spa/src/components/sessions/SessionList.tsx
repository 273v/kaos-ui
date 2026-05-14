import { useParams } from "@tanstack/react-router";

import { useSessionList } from "@/hooks/use-session-list";
import { SessionListItem } from "./SessionListItem";

/**
 * Vertical session list shown inside the sidebar.
 *
 * Highlights the active route's `:id` param (TanStack Router supplies
 * an empty object when the user is on /sessions/ without an id).
 */
export function SessionList() {
  const params = useParams({ strict: false });
  const activeId = (params as { id?: string }).id;

  const query = useSessionList();

  if (query.isLoading) {
    return <div className="px-3 py-2 text-xs text-muted-foreground">Loading sessions…</div>;
  }
  if (query.isError) {
    return (
      <div className="px-3 py-2 text-xs text-destructive">
        Couldn't load sessions. Check the backend logs.
      </div>
    );
  }

  const items = query.data?.sessions ?? [];
  if (items.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        No conversations yet. Start one with “New chat”.
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-0.5 px-2">
      {items.map((s) => (
        <li key={s.id}>
          <SessionListItem session={s} active={s.id === activeId} />
        </li>
      ))}
    </ul>
  );
}
