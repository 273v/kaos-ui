/**
 * Run Inspector — fixed-position right-side debug overlay combining:
 *
 *   - `<CostStrip>`     header with live $ / token / call counts
 *   - `<FilterChips>`   category filters
 *   - `<EventsLog>`     scrollable event log with per-row JsonTree expand
 *
 * Modeled after the kaos-agents JSONL viewer (`kaos_agents.examples.viewer`)
 * but adapted to a live SSE stream rather than a post-hoc JSONL file.
 *
 * Mount it at the bottom of your chat route. Toggle visibility via the
 * `open` prop (the example app drives it from `?debug=true`).
 */

import { Bug, X } from "lucide-react";
import { useState } from "react";

import type { DebugEvent } from "../hooks/use-send-message.js";
import { CostStrip } from "./CostStrip.js";
import { EventsLog } from "./EventsLog.js";
import { type EventCategory, FilterChips } from "./FilterChips.js";

export interface RunInspectorProps {
  events: ReadonlyArray<DebugEvent>;
  open: boolean;
  onClose: () => void;
  /** Visual variant — `"sidebar"` (fixed right rail) or `"inline"` (flow). */
  variant?: "sidebar" | "inline";
  /** Title shown in the header. */
  title?: string;
}

export function RunInspector({
  events,
  open,
  onClose,
  variant = "sidebar",
  title = "Run Inspector",
}: RunInspectorProps) {
  const [filter, setFilter] = useState<ReadonlySet<EventCategory>>(() => new Set());
  if (!open) return null;

  const className =
    variant === "sidebar"
      ? "fixed bottom-4 right-4 z-30 w-[440px] h-[70vh] bg-card border border-border rounded-md shadow-lg flex flex-col"
      : "w-full h-full bg-card border border-border flex flex-col";

  return (
    <aside className={className} aria-label={title}>
      <header className="px-3 py-2 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bug className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">{title}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {events.length} event{events.length === 1 ? "" : "s"}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Close run inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <CostStrip events={events} className="border-b border-border" />
      <FilterChips active={filter} onChange={setFilter} />
      <EventsLog events={events} filter={filter} />
    </aside>
  );
}
