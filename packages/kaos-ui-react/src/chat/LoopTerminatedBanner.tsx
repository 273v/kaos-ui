/**
 * AgenticLoop terminal banner (kaos-agents 0.1.0a4).
 *
 * Renders below an assistant message after the loop terminates. The
 * "satisfied" reason renders nothing — the answer + GoalCheckBadge are
 * already the user signal. Other reasons surface as a small banner so
 * the user understands WHY the loop ended (cost cap, stuck, etc).
 *
 * The seven reasons map to three visual tiers:
 *   - **success**: "satisfied" (renders nothing).
 *   - **info**:    "insufficient_evidence" (the agent gave up cleanly).
 *   - **warn**:    every other reason — surface that the loop was
 *                   cut short, with a one-line explanation.
 */

import { AlertTriangle, Info } from "lucide-react";

import type { LoopTerminationSnapshot } from "../lib/chat-state.js";

interface Props {
  termination?: LoopTerminationSnapshot;
}

const REASON_COPY: Record<
  LoopTerminationSnapshot["reason"],
  { title: string; subtitle: string; tier: "success" | "info" | "warn" }
> = {
  satisfied: {
    title: "Satisfied",
    subtitle: "Critic accepted the answer.",
    tier: "success",
  },
  insufficient_evidence: {
    title: "Not enough evidence",
    subtitle: "The agent stopped because the available sources can't answer this.",
    tier: "info",
  },
  max_iterations: {
    title: "Iteration limit hit",
    subtitle: "The agent ran out of replanning attempts. Try a narrower question.",
    tier: "warn",
  },
  cost_exceeded: {
    title: "Cost limit hit",
    subtitle: "The agent exceeded the per-turn cost cap and stopped.",
    tier: "warn",
  },
  wall_clock_exceeded: {
    title: "Time limit hit",
    subtitle: "The agent exceeded the per-turn wall-clock cap.",
    tier: "warn",
  },
  stuck_no_progress: {
    title: "No further progress",
    subtitle: "The agent's most recent iteration made no new headway.",
    tier: "warn",
  },
  user_interrupt: {
    title: "Interrupted",
    subtitle: "You stopped the agent mid-turn.",
    tier: "warn",
  },
};

function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function formatWallClock(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function LoopTerminatedBanner({ termination }: Props) {
  if (!termination) return null;
  const meta = REASON_COPY[termination.reason];
  if (meta.tier === "success") return null;

  const Icon = meta.tier === "warn" ? AlertTriangle : Info;
  const containerCls =
    meta.tier === "warn"
      ? "border-warn/40 bg-warn/5 text-warn-foreground"
      : "border-border bg-muted/40 text-muted-foreground";

  return (
    <div className={`mt-2 rounded-md border ${containerCls} p-2 text-xs`}>
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="space-y-0.5">
          <p>
            <span className="font-medium text-foreground">{meta.title}.</span>{" "}
            <span>{meta.subtitle}</span>
          </p>
          <p className="tabular-nums opacity-70">
            {termination.iterations_used} iteration
            {termination.iterations_used === 1 ? "" : "s"} ·{" "}
            {formatCost(termination.cost_usd)} ·{" "}
            {formatWallClock(termination.wall_clock_ms)}
          </p>
        </div>
      </div>
    </div>
  );
}
