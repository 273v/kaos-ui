// Debug overlay shown when `?debug=true` is in the URL.
//
// Renders every raw kaos-agents event as it arrives — useful for
// demoing the full wire surface (15 types + span cartesian) without
// digging into DevTools Network. Per PRD G3 + UX-LANGUAGE.md.

import { useSearch } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import type { DebugEvent } from "@/hooks/use-send-message";

interface Props {
  events: DebugEvent[];
}

export function DebugPanel({ events }: Props) {
  const search = useSearch({ strict: false }) as { debug?: string | boolean };
  const enabled = search.debug === "true" || search.debug === true;
  const ref = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to the latest event. LOW #3 — pre-fix the deps were
  // `[]` so this only ran on mount and never followed new events.
  // `events.length` is the signal; biome strips it as "unread" otherwise.
  // biome-ignore lint/correctness/useExhaustiveDependencies: events.length change is the trigger to scroll, not something the effect reads.
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  if (!enabled) return null;

  return (
    <aside
      className="fixed bottom-4 right-4 z-30 w-[420px] h-[60vh] bg-card border border-border rounded-md shadow-none flex flex-col text-xs font-mono"
      aria-label="Event debug panel"
    >
      <header className="px-3 py-2 border-b border-border flex items-center justify-between">
        <span className="font-sans font-medium text-foreground">Event stream</span>
        <span className="text-muted-foreground tabular-nums">{events.length} events</span>
      </header>
      <div ref={ref} className="flex-1 overflow-y-auto px-2 py-1 space-y-1">
        {events.length === 0 && (
          <p className="text-muted-foreground italic font-sans px-2 py-2">
            No events yet — send a message to see them stream in.
          </p>
        )}
        {events.map(({ _id, event }) => (
          <div
            key={_id}
            className="rounded-sm px-2 py-1 hover:bg-muted/60 border-l-2 border-accent/40 break-words"
          >
            <span className="text-accent">{event.type}</span>
            {"subject" in event && "phase" in event && (
              <span className="text-muted-foreground ml-1">
                ({event.subject}/{event.phase})
              </span>
            )}
          </div>
        ))}
      </div>
      <footer className="px-3 py-1.5 border-t border-border text-[10px] text-muted-foreground font-sans">
        Drop <code>?debug=true</code> from the URL to hide.
      </footer>
    </aside>
  );
}
