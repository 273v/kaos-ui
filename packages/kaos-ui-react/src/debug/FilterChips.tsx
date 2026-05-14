/**
 * Event-type filter row for the events log. Users tick categories to
 * include; an empty selection means "all visible" (the common case).
 *
 * Categories collapse the 15 wire types into 5 functional buckets so
 * the chip row stays readable. Use `<EventsLog filter>` to consume
 * the active set.
 */

import type { EventType } from "../lib/events.js";

export type EventCategory = "text" | "thinking" | "tool" | "span" | "usage" | "citation" | "error";

export const CATEGORY_TO_TYPES: Readonly<Record<EventCategory, ReadonlyArray<EventType>>> = {
  text: ["text_delta", "turn_summary"],
  thinking: ["thinking_delta"],
  tool: ["tool_call_args_delta", "tool_call_approval_required"],
  span: ["span", "intent_classified", "plan_proposed", "memory_event"],
  usage: ["usage_observed", "budget_exceeded"],
  citation: ["citation_found"],
  error: ["run_error", "evidence_insufficient", "grounding_refusal_triggered"],
};

const CATEGORY_LABELS: Record<EventCategory, string> = {
  text: "Text",
  thinking: "Thinking",
  tool: "Tools",
  span: "Spans",
  usage: "Usage",
  citation: "Citations",
  error: "Errors",
};

interface Props {
  /** Set of active categories. Empty set means "show everything". */
  active: ReadonlySet<EventCategory>;
  onChange: (next: ReadonlySet<EventCategory>) => void;
}

export function FilterChips({ active, onChange }: Props) {
  const toggle = (cat: EventCategory) => {
    const next = new Set(active);
    if (next.has(cat)) next.delete(cat);
    else next.add(cat);
    onChange(next);
  };
  return (
    <div className="flex flex-wrap gap-1.5 px-3 py-2 text-[11px]">
      {(Object.keys(CATEGORY_LABELS) as EventCategory[]).map((cat) => {
        const on = active.has(cat);
        return (
          <button
            key={cat}
            type="button"
            onClick={() => toggle(cat)}
            aria-pressed={on}
            className={`px-2 py-0.5 rounded-full border transition-colors ${
              on
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-card text-muted-foreground border-border hover:bg-muted"
            }`}
          >
            {CATEGORY_LABELS[cat]}
          </button>
        );
      })}
      {active.size > 0 && (
        <button
          type="button"
          onClick={() => onChange(new Set())}
          className="ml-auto text-muted-foreground hover:text-foreground"
        >
          Clear
        </button>
      )}
    </div>
  );
}
