/**
 * Inline plan card rendered under an assistant `<Message>`.
 *
 * The user should always know what the agent is about to do, what it
 * has done so far, and which steps failed. Pre-VIS-3 the SPA showed a
 * single grey banner saying "plan proposed (we don't render this yet)"
 * — utterly opaque. This card replaces that with a per-step list:
 *
 *     1.  ✓  Search Federal Register for "cyber*"          tool: fr-search
 *     2.  ◐  Fetch full text of FR Doc 2024-11116          tool: fr-get-content
 *     3.  ·  Extract defined terms                          tool: (none)
 *
 *   ✓ = done    ◐ = running    · = waiting    ✗ = error
 *
 * The card respects the same expand-when-streaming / expand-on-error
 * defaults as `ToolCallBlock` so the user sees what's happening live
 * and gets called out when a step fails.
 */

import { Check, ChevronDown, ChevronRight, Circle, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { PlanSnapshot, PlanStep } from "../lib/chat-state.js";

interface Props {
  plan: PlanSnapshot;
  /** Start expanded. Default false. */
  defaultOpen?: boolean;
}

const STATUS_LABEL: Record<PlanStep["status"], string> = {
  waiting: "queued",
  running: "running",
  done: "done",
  error: "failed",
};

function StepStatusIcon({ status }: { status: PlanStep["status"] }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />;
    case "done":
      return <Check className="h-3.5 w-3.5 text-foreground" />;
    case "error":
      return <X className="h-3.5 w-3.5 text-destructive" />;
    default:
      return <Circle className="h-3 w-3 text-muted-foreground/60" strokeWidth={2.5} />;
  }
}

export function PlanCard({ plan, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  const totalSteps = plan.steps.length;
  const doneSteps = plan.steps.filter((s) => s.status === "done").length;
  const errorSteps = plan.steps.filter((s) => s.status === "error").length;
  const runningStep = plan.steps.find((s) => s.status === "running");

  const summary =
    errorSteps > 0
      ? `${errorSteps} of ${totalSteps} step${totalSteps === 1 ? "" : "s"} failed`
      : runningStep
        ? `step ${plan.steps.indexOf(runningStep) + 1} of ${totalSteps}: ${runningStep.description}`
        : doneSteps === totalSteps
          ? `${totalSteps} step${totalSteps === 1 ? "" : "s"} done`
          : `${doneSteps} of ${totalSteps} step${totalSteps === 1 ? "" : "s"} done`;

  return (
    <div className="rounded-md border border-border bg-card overflow-hidden text-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full text-left px-3 py-1.5 flex items-start gap-2 hover:bg-muted/60"
        title={`Plan (${plan.strategy}): ${totalSteps} step${totalSteps === 1 ? "" : "s"}`}
      >
        <span className="mt-0.5 text-muted-foreground">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </span>
        <span className="flex-1 min-w-0">
          <span className="text-xs font-medium">Plan</span>
          {plan.strategy && plan.strategy !== "direct" && (
            <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground">
              {plan.strategy}
            </span>
          )}
          <span className="ml-2 text-xs text-muted-foreground italic">→ {summary}</span>
        </span>
      </button>
      {open && (
        <ol className="px-3 py-2 text-xs space-y-1.5 border-t border-border/70 list-none">
          {plan.steps.map((step, idx) => (
            <li key={step.step_id} className="flex items-start gap-2">
              <span className="mt-0.5 shrink-0 w-4 text-muted-foreground text-[10px] tabular-nums">
                {idx + 1}.
              </span>
              <span className="mt-0.5 shrink-0">
                <StepStatusIcon status={step.status} />
              </span>
              <span className="flex-1 min-w-0">
                <span className={step.status === "error" ? "text-destructive" : "text-foreground"}>
                  {step.description}
                </span>
                {step.tool_name && (
                  <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                    {step.tool_name}
                  </span>
                )}
                {step.result_preview && (
                  <span className="block text-[10px] text-muted-foreground italic mt-0.5">
                    → {step.result_preview.slice(0, 200)}
                    {step.result_preview.length > 200 ? "…" : ""}
                  </span>
                )}
                <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground/70">
                  {STATUS_LABEL[step.status]}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
