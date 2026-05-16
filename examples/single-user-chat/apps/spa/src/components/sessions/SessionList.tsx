import { useLocalStorage } from "@273v/kaos-ui-react/hooks";
import { useParams } from "@tanstack/react-router";
import { ArrowDownAZ, Clock, Star } from "lucide-react";
import { useMemo } from "react";

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

// Time-bucket headers per AUDIT.md §S1 + RESEARCH-sota.md §1. Five
// buckets keep scanning fast without folder-style structure (which
// no legal-research competitor uses). Buckets are computed against
// `last_message_at || created_at` (the same ts our default sort
// uses) so a "Today" header always matches the rows below it.
type Bucket = {
  id: "today" | "yesterday" | "prev_7" | "prev_30" | "older";
  label: string;
  // upper-exclusive ms threshold relative to "now"; null = catch-all.
  cutoffMs: number | null;
};

const MS_PER_DAY = 24 * 60 * 60 * 1000;

const BUCKETS: ReadonlyArray<Bucket> = [
  { id: "today", label: "Today", cutoffMs: MS_PER_DAY },
  { id: "yesterday", label: "Yesterday", cutoffMs: 2 * MS_PER_DAY },
  { id: "prev_7", label: "Previous 7 days", cutoffMs: 7 * MS_PER_DAY },
  { id: "prev_30", label: "Previous 30 days", cutoffMs: 30 * MS_PER_DAY },
  { id: "older", label: "Older", cutoffMs: null },
];

function bucketTs(s: SessionSummary): number {
  return s.last_message_at
    ? new Date(s.last_message_at).valueOf()
    : new Date(s.created_at).valueOf();
}

function bucketize(
  items: SessionSummary[],
  now: number,
): { bucket: Bucket; items: SessionSummary[] }[] {
  // Truncate "now" to the start of the local day so a session from
  // 30 minutes ago consistently lands in Today even if "now" rolled
  // past midnight while the user was on the page.
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const baseline = startOfToday.valueOf();

  const out: { bucket: Bucket; items: SessionSummary[] }[] = BUCKETS.map(
    (b) => ({ bucket: b, items: [] }),
  );
  for (const s of items) {
    const age = Math.max(0, baseline - bucketTs(s));
    // Today = anything from `baseline` forward (incl. future-ish
    // clock skew); anything before today falls into yesterday-or-older.
    let idx = 0;
    if (bucketTs(s) >= baseline) {
      idx = 0;
    } else {
      idx = BUCKETS.findIndex((b) => b.cutoffMs == null || age < b.cutoffMs);
      if (idx < 0) idx = BUCKETS.length - 1;
    }
    out[idx]?.items.push(s);
  }
  return out.filter((b) => b.items.length > 0);
}

export function SessionList({ archived = false }: Props) {
  const params = useParams({ strict: false });
  const activeId = (params as { id?: string }).id;
  // Sort + filter both persist via localStorage so the user's
  // preference survives reloads.
  const [sort, setSort] = useLocalStorage<SortMode>("kaos:session-sort", "last_used");
  const [starredOnly, setStarredOnly] = useLocalStorage("kaos:session-starred-only", false);

  const query = useSessionList(archived);

  const items = useMemo(() => {
    const all = sortSessions(query.data?.sessions ?? [], sort);
    return starredOnly ? all.filter((s) => s.starred) : all;
  }, [query.data?.sessions, sort, starredOnly]);

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
  const SortIcon = SORT_LABELS[sort].icon;
  const isEmpty = items.length === 0;
  return (
    <>
      {!archived && (
        <div className="px-3 pb-1 pt-2 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setStarredOnly((v) => !v)}
            aria-pressed={starredOnly}
            title={starredOnly ? "Show all sessions" : "Show starred sessions only"}
            className={
              "inline-flex items-center gap-1 text-[10px] uppercase tracking-wide rounded-md px-1.5 py-0.5 transition-colors " +
              (starredOnly ? "text-warn bg-muted" : "text-muted-foreground hover:text-foreground")
            }
          >
            <Star
              className="h-3 w-3"
              fill={starredOnly ? "currentColor" : "none"}
              strokeWidth={starredOnly ? 1.5 : 2}
            />
            Starred
          </button>
          <label className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground cursor-pointer relative">
            <SortIcon className="h-3 w-3" />
            <span className="uppercase tracking-wide">{SORT_LABELS[sort].label}</span>
            <select
              id="sidebar-sort"
              name="sidebar-sort"
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
      {isEmpty ? (
        <div className="px-3 py-2 text-xs text-muted-foreground italic">
          {archived
            ? "Nothing archived."
            : starredOnly
              ? "No starred sessions. Star a row to pin it here."
              : "No conversations yet. Start one with “New chat”."}
        </div>
      ) : sort === "last_used" && !archived ? (
        // Time-bucketed view — only when the user is on the default
        // chronological sort. Other sort modes are explicit user
        // overrides and we respect them as flat lists.
        <div className="flex flex-col gap-1 px-2">
          {bucketize(items, Date.now()).map(({ bucket, items: rows }) => (
            <section key={bucket.id} aria-label={bucket.label}>
              <h3 className="px-2 pt-2 pb-0.5 text-[10px] uppercase tracking-wide text-foreground/70">
                {bucket.label}
              </h3>
              <ul className="flex flex-col gap-0.5">
                {rows.map((s) => (
                  <li key={s.id}>
                    <SessionListItem session={s} active={s.id === activeId} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <ul className="flex flex-col gap-0.5 px-2">
          {items.map((s) => (
            <li key={s.id}>
              <SessionListItem session={s} active={s.id === activeId} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
