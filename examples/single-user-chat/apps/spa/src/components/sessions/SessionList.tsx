import { useParams } from "@tanstack/react-router";

import { useSessionList } from "@/hooks/use-session-list";
import { SessionListItem } from "./SessionListItem";

interface Props {
  /** Show archived sessions instead of active ones. */
  archived?: boolean;
}

/**
 * Vertical session list shown inside the sidebar. Renders the active
 * namespace by default; pass `archived` to render the archived list.
 *
 * Highlights the active route's `:id` param (TanStack Router supplies
 * an empty object when the user is on /sessions/ without an id).
 */
export function SessionList({ archived = false }: Props) {
  const params = useParams({ strict: false });
  const activeId = (params as { id?: string }).id;

  const query = useSessionList(archived);

  if (query.isLoading) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        Loading{archived ? " archived" : ""}…
      </div>
    );
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
        {archived ? "Nothing archived." : "No conversations yet. Start one with “New chat”."}
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
