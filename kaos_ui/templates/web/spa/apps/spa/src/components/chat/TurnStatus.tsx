/**
 * TurnStatus — small, muted activity pill shown above the streaming
 * assistant message. Reflects the most recent kaos-agents lifecycle
 * event so the user can see WHAT the agent is doing during the
 * (potentially multi-second) gap before tokens start arriving.
 *
 * Driven by `chat.tsx` — that's where the SSE event handler maps
 * each wire event to a status string. We only render here.
 *
 * Events we currently surface (out of the 21 kaos-agents emits):
 *   - turn_start                   → "Thinking…"
 *   - intent_classified            → "Classifying intent…"  (transient)
 *   - tool_call_start              → "Running tool: X…"
 *   - tool_call_result             → "Tool finished"        (transient)
 *   - step_start (PLAN pattern)    → "Step N: <description>"
 *   - run_error                    → red error pill
 *
 * Phase B will add: tool_call_approval_required (modal),
 * plan_proposed (timeline), citation_found (inline chips),
 * grounding_refusal_triggered (banner). For now those fall through
 * to the default "Generating response…" until tokens arrive.
 */

import { cn } from "@{{KAOS_NPM_SLUG}}/ui/lib/utils";
import { AlertCircle, Loader2 } from "lucide-react";

export type TurnStatusKind = "info" | "tool" | "error";

export interface TurnStatusValue {
  kind: TurnStatusKind;
  text: string;
}

interface TurnStatusProps {
  status: TurnStatusValue;
}

export function TurnStatus({ status }: TurnStatusProps) {
  const isError = status.kind === "error";
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs",
        isError
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-border bg-secondary text-muted-foreground",
      )}
      role="status"
      aria-live="polite"
    >
      {isError ? (
        <AlertCircle className="h-3 w-3 shrink-0" />
      ) : (
        <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
      )}
      <span>{status.text}</span>
    </div>
  );
}
