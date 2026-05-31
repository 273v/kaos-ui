/**
 * Streaming events log — replaces the example app's thin `DebugPanel`.
 *
 * Each row shows the wire-event type + (for span events) the
 * subject/phase discriminator. Click a row to expand the full payload
 * via `<JsonTree>`.
 *
 * Optional `filter` set (from `<FilterChips>`) narrows the visible
 * types; an empty filter set shows everything.
 *
 * Auto-scrolls to the latest event as long as the user is already
 * near the bottom (avoids yanking them away when they're inspecting
 * an older event).
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { DebugEvent } from "../hooks/use-send-message.js";
import type { EventType, KaosAgentEvent, SpanEvent } from "../lib/events.js";
import { CATEGORY_TO_TYPES, type EventCategory } from "./FilterChips.js";
import { JsonTree } from "./JsonTree.js";

export interface EventsLogProps {
  events: ReadonlyArray<DebugEvent>;
  /** Categories the user has filtered to; empty set = show everything. */
  filter?: ReadonlySet<EventCategory>;
  className?: string;
}

function isSpan(ev: KaosAgentEvent): ev is SpanEvent {
  return ev.type === "span";
}

function buildActiveTypes(filter: ReadonlySet<EventCategory>): Set<EventType> | null {
  if (filter.size === 0) return null;
  const out = new Set<EventType>();
  for (const cat of filter) {
    for (const t of CATEGORY_TO_TYPES[cat]) out.add(t);
  }
  return out;
}

export function EventsLog({ events, filter, className }: EventsLogProps) {
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set());
  const ref = useRef<HTMLDivElement | null>(null);

  const activeTypes = useMemo(() => buildActiveTypes(filter ?? new Set()), [filter]);
  const visible = useMemo(
    () => (activeTypes ? events.filter((e) => activeTypes.has(e.event.type as EventType)) : events),
    [events, activeTypes],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: events.length change is the auto-scroll trigger; we don't read it inside.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Only auto-scroll when the user is already near the bottom — gives
    // them room to inspect older events without getting yanked back.
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [visible.length]);

  return (
    <div
      ref={ref}
      role="log"
      className={`flex-1 overflow-y-auto text-xs font-mono ${className ?? ""}`}
      aria-label="Events log"
    >
      {visible.length === 0 ? (
        <p className="text-muted-foreground italic px-3 py-2 font-sans">
          No events to show. Send a message to see them stream in.
        </p>
      ) : (
        visible.map(({ _id, event }) => {
          const isOpen = expanded.has(_id);
          return (
            <div
              key={_id}
              className="border-l-2 border-border hover:border-primary/40 transition-colors"
            >
              <button
                type="button"
                onClick={() => {
                  const next = new Set(expanded);
                  if (next.has(_id)) next.delete(_id);
                  else next.add(_id);
                  setExpanded(next);
                }}
                className="w-full text-left px-3 py-1 hover:bg-muted/60"
              >
                <span className="text-foreground">{event.type}</span>
                {isSpan(event) && (
                  <span className="text-muted-foreground ml-1">
                    ({event.subject}/{event.phase})
                  </span>
                )}
                {event.type === "text_delta" && event.content && (
                  <span className="text-muted-foreground ml-1 truncate inline-block max-w-[60%] align-bottom">
                    "{event.content.slice(0, 80)}"
                  </span>
                )}
              </button>
              {isOpen && (
                <div className="px-3 pb-2 pt-1">
                  <JsonTree value={event} initialDepth={3} />
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
