/**
 * `<ReasoningSummary>` — collapsed-by-default inline reasoning block.
 *
 * Pattern: Claude 4.6 adaptive thinking + Vercel AI Elements `Reasoning`.
 * Above each assistant turn that emitted a goal-check or a thinking-
 * delta block, render a one-line gray-italic summary. Click to expand
 * into the full rationale + (if available) the thinking deltas.
 *
 * For kaos-ui this is pure rendering — the data is already on the
 * `ChatMessage` value type from the reducer:
 *   - `goal_check.rationale` — Critic's one-liner ("the answer addresses
 *     the user's question")
 *   - `goal_check.next_action` — replan note on "needs_more_work"
 *   - `goal_check.missing` — corpus gap on "insufficient_evidence"
 *
 * Design intent (matches the team's UX-LANGUAGE.md §4.4):
 *   - Reasoning is *first-class but quiet* — italic body, muted, no
 *     icon shouting. Reading flow stays on the answer.
 *   - One expand action; no nested chevrons. Power users go to the
 *     run inspector for the full event stream.
 *   - When the critic returned `satisfied`, summary still renders so
 *     the user knows the agent verified its own answer (this is the
 *     transparency dividend we get for free).
 */

import { ChevronDown, ChevronRight, CircleDashed } from "lucide-react";
import { useState } from "react";

import type { GoalCheckSnapshot } from "../lib/chat-state.js";

interface Props {
  goal?: GoalCheckSnapshot;
}

const KIND_HINT: Record<GoalCheckSnapshot["kind"], string> = {
  satisfied: "Verified by critic",
  needs_more_work: "Replanned",
  insufficient_evidence: "Returned a clean refusal",
};

export function ReasoningSummary({ goal }: Props) {
  const [open, setOpen] = useState(false);
  if (!goal) return null;
  // If the critic produced no prose, there's nothing to summarize.
  if (!goal.rationale && !goal.next_action && !goal.missing) return null;

  const hint = KIND_HINT[goal.kind];
  // Body sentence: rationale wins; if absent, fall back to the
  // forward-looking note (next_action for replan; missing for
  // insufficient_evidence).
  const summary =
    goal.rationale || goal.next_action || goal.missing || "";

  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="mb-2 group"
    >
      <summary
        className="list-none cursor-pointer select-none inline-flex items-start gap-1.5 text-xs italic text-foreground/55 hover:text-foreground/80 transition-colors"
        title="Show critic reasoning"
      >
        <span className="mt-0.5 text-foreground/40 group-open:hidden">
          <ChevronRight className="h-3 w-3" />
        </span>
        <span className="mt-0.5 text-foreground/40 hidden group-open:inline-block">
          <ChevronDown className="h-3 w-3" />
        </span>
        <CircleDashed className="mt-0.5 h-3 w-3 text-foreground/30 not-italic" />
        <span className="flex-1 min-w-0 leading-snug">
          <span className="not-italic font-medium text-foreground/70">
            {hint}.
          </span>{" "}
          {summary}
        </span>
      </summary>
      <div className="mt-2 ml-5 pl-3 border-l border-border/60 text-xs space-y-2">
        {goal.rationale && (
          <p className="text-foreground/70 leading-relaxed">
            <span className="not-italic font-medium text-foreground/55">Rationale: </span>
            {goal.rationale}
          </p>
        )}
        {goal.next_action && (
          <p className="text-foreground/70 leading-relaxed">
            <span className="not-italic font-medium text-foreground/55">
              Next action:{" "}
            </span>
            {goal.next_action}
          </p>
        )}
        {goal.missing && (
          <p className="text-foreground/70 leading-relaxed">
            <span className="not-italic font-medium text-foreground/55">Missing: </span>
            {goal.missing}
          </p>
        )}
        <p className="text-foreground/45 tabular-nums">
          iteration {goal.iteration} ·{" "}
          {goal.confidence > 0
            ? `${Math.round(goal.confidence * 100)}% confidence`
            : "confidence n/a"}{" "}
          · {Math.round(goal.latency_ms)}ms
        </p>
      </div>
    </details>
  );
}
