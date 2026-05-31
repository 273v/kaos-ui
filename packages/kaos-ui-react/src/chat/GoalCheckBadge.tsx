/**
 * Critic verdict badge (kaos-agents 0.1.0a4 AgenticLoop).
 *
 * Renders below the assistant text when the per-iteration GoalChecker
 * emitted a verdict. Three colors map to three states:
 *
 *   - **green** ("satisfied")             — the answer addresses the
 *                                            user's question; loop ended.
 *   - **amber** ("needs_more_work")       — loop will replan + retry
 *                                            (shows `next_action`).
 *   - **gray**  ("insufficient_evidence") — the corpus can't answer
 *                                            (shows `missing`).
 *
 * Click to expand into rationale + per-call cost / latency.
 */

import { CheckCircle2, CircleAlert, CircleDashed } from "lucide-react";
import { useState } from "react";

import type { GoalCheckSnapshot } from "../lib/chat-state.js";

interface Props {
  /** Critic verdict from the per-turn `goal_checked` event. */
  goal?: GoalCheckSnapshot;
}

function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const KIND_LABELS: Record<GoalCheckSnapshot["kind"], string> = {
  satisfied: "Answered",
  needs_more_work: "Replanning",
  insufficient_evidence: "Can't answer",
};

export function GoalCheckBadge({ goal }: Props) {
  const [open, setOpen] = useState(false);
  if (!goal) return null;

  const { kind, rationale, next_action, missing, confidence, iteration, cost_usd, latency_ms } =
    goal;

  // Color + icon driven by kind. Green/amber/gray per the design doc.
  const variants: Record<GoalCheckSnapshot["kind"], { cls: string; Icon: typeof CheckCircle2 }> = {
    satisfied: {
      cls: "border-success/40 bg-success/5 text-success-foreground hover:bg-success/10",
      Icon: CheckCircle2,
    },
    needs_more_work: {
      cls: "border-warn/40 bg-warn/5 text-warn-foreground hover:bg-warn/10",
      Icon: CircleAlert,
    },
    insufficient_evidence: {
      cls: "border-border bg-muted/50 text-muted-foreground hover:bg-muted",
      Icon: CircleDashed,
    },
  };
  const { cls, Icon } = variants[kind];

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={[
          "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
          "border tabular-nums transition-colors",
          cls,
        ].join(" ")}
        aria-expanded={open}
        title={`Goal check (iteration ${iteration})`}
      >
        <Icon className="h-3 w-3" />
        <span className="font-medium">{KIND_LABELS[kind]}</span>
        <span className="opacity-60">· {(confidence * 100).toFixed(0)}%</span>
      </button>
      {open && (
        <div className="mt-1 max-w-md space-y-1.5 rounded-md border border-border bg-muted/30 p-3 text-xs">
          {rationale && <p className="text-muted-foreground">{rationale}</p>}
          {kind === "needs_more_work" && next_action && (
            <p>
              <span className="font-medium text-foreground">Next: </span>
              <span className="text-muted-foreground">{next_action}</span>
            </p>
          )}
          {kind === "insufficient_evidence" && missing && (
            <p>
              <span className="font-medium text-foreground">Missing: </span>
              <span className="text-muted-foreground">{missing}</span>
            </p>
          )}
          <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 tabular-nums">
            <dt className="text-muted-foreground">Iteration</dt>
            <dd>{iteration}</dd>
            <dt className="text-muted-foreground">Critic</dt>
            <dd>
              {formatCost(cost_usd)} · {formatLatency(latency_ms)}
            </dd>
          </dl>
        </div>
      )}
    </div>
  );
}
