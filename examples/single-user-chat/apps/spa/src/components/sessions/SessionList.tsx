import { useParams } from "@tanstack/react-router";
import { ArrowDownAZ, Clock, Star } from "lucide-react";
import { useMemo, useState } from "react";

import { useSessionList } from "@/hooks/use-session-list";
import type { SessionSummary } from "@/lib/api-types";
import { SessionListItem } from "./SessionListItem";

type SortMode = "last_used" | "created" | "starred_first";

const SORT_LABELS: Record<SortMode, { label: string; icon: typeof Clock }> = {
  last_used: { label: "Last used", icon: Clock },
  created: { label: "Created", icon: ArrowDownAZ },
  starred_first: { label: "Starred first", icon: Star },
};

interface Props {
  /** Show archived sessions instead of active ones. */
  archived?: boolean;
}

function sortSessions(items: SessionSummary[], mode: SortMode): SessionSummary[] {
  const tsLast = (s: SessionSummary) =>
    s.last_message_at ? new Date(s.last_message_at).valueOf() : new Date(s.created_at).valueOf();
  const tsCreated = (s: SessionSummary) => new Date(s.created_at).valueOf();

  switch (mode) {
    case "last_used":
      return [...items].sort((a, b) => tsLast(b) - tsLast(a));
    case "created":
      return [...items].sort((a, b) => tsCreated(b) - tsCreated(a));
    case "starred_first":
      return [...items].sort((a, b) => {
        if (a.starred !== b.starred) return a.starred ? -1 : 1;
        return tsLast(b) - tsLast(a);
      });
  }
}

export function SessionList({ archived = false }: Props) {
  const params = useParams({ strict: false });
  const activeId = (params as { id?: string }).id;
  const [sort, setSort] = useState<SortMode>("last_used");

  const query = useSessionList(archived);

  const items = useMemo(
    () => sortSessions(query.data?.sessions ?? [], sort),
    [query.data?.sessions, sort],
  );

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
  if (items.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        {archived ? "Nothing archived." : "No conversations yet. Start one with “New chat”."}
      </div>
    );
  }

  const SortIcon = SORT_LABELS[sort].icon;
  return (
    <>
      {!archived && (
        <div className="px-3 pb-1 pt-2 flex items-center justify-end">
          <label className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground cursor-pointer relative">
            <SortIcon className="h-3 w-3" />
            <span className="uppercase tracking-wide">{SORT_LABELS[sort].label}</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortMode)}
              className="absolute inset-0 opacity-0 cursor-pointer"
              aria-label="Sort sessions"
            >
              <option value="last_used">Last used</option>
              <option value="created">Created</option>
              <option value="starred_first">Starred first</option>
            </select>
          </label>
        </div>
      )}
      <ul className="flex flex-col gap-0.5 px-2">
        {items.map((s) => (
          <li key={s.id}>
            <SessionListItem session={s} active={s.id === activeId} />
          </li>
        ))}
      </ul>
    </>
  );
}
