/**
 * Per-turn tool-policy transparency badge (TR-9).
 *
 * Renders above an assistant message when the backend's TurnToolPolicy
 * planner (kaos-ui example, TR-5) emitted a `tool_policy_decided`
 * event. Shows the narrowed group set the agent had access to for
 * THIS turn and opens a popover with the planner's reasoning,
 * confidence, and cost.
 *
 * Renders nothing when no policy is attached — most kaos-agents
 * deployments don't run the planner, so the badge gracefully no-ops.
 */

import { Filter, Shield } from "lucide-react";
import { useState } from "react";

import type { ToolPolicySnapshot } from "../lib/chat-state.js";

interface Props {
  /** Tool-policy snapshot from the per-turn `tool_policy_decided` event. */
  policy?: ToolPolicySnapshot;
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

export function ToolPolicyBadge({ policy }: Props) {
  const [open, setOpen] = useState(false);
  if (!policy) return null;

  const {
    turn_groups,
    ceiling_groups,
    reasoning,
    confidence,
    fell_back_to_ceiling,
    cost_usd,
    latency_ms,
  } = policy;
  const isFallback = fell_back_to_ceiling;
  const groupsLabel = turn_groups.length === 0 ? "no tools" : turn_groups.join(", ");

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={[
          "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
          "border tabular-nums transition-colors",
          isFallback
            ? "border-warn/40 bg-warn/5 text-warn-foreground hover:bg-warn/10"
            : "border-border bg-muted/50 text-muted-foreground hover:bg-muted",
        ].join(" ")}
        aria-expanded={open}
        title={isFallback ? "Planner abdicated — using full ceiling" : "Per-turn tool policy"}
      >
        {isFallback ? <Shield className="h-3 w-3" /> : <Filter className="h-3 w-3" />}
        <span className="font-medium">Tools:</span>
        <span>{groupsLabel}</span>
        {!isFallback && <span className="opacity-60">· {(confidence * 100).toFixed(0)}%</span>}
      </button>
      {open && (
        <div className="mt-1 rounded-md border border-border bg-muted/30 p-3 text-xs space-y-1.5 max-w-md">
          <p className="text-muted-foreground">{reasoning}</p>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 tabular-nums">
            <dt className="text-muted-foreground">Confidence</dt>
            <dd>{(confidence * 100).toFixed(0)}%</dd>
            <dt className="text-muted-foreground">Ceiling</dt>
            <dd>{ceiling_groups.join(", ") || "(none)"}</dd>
            <dt className="text-muted-foreground">This turn</dt>
            <dd>{turn_groups.join(", ") || "(none)"}</dd>
            <dt className="text-muted-foreground">Planner</dt>
            <dd>
              {formatCost(cost_usd)} · {formatLatency(latency_ms)}
            </dd>
          </dl>
        </div>
      )}
    </div>
  );
}
