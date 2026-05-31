/**
 * Inline capability-approval card (kaos-agents 0.1.0a4 AgenticLoop).
 *
 * Renders when the loop has emitted a `capability_requested` event and is
 * waiting for the user's decision. Four actions per the design doc:
 *
 *   - **Enable for this turn**  — let the loop continue with the requested
 *                                  groups added to `allowed_groups`. Reset
 *                                  on the next turn.
 *   - **Enable for session**     — persist the change via PATCH tool-set.
 *   - **Deny + continue**        — let the loop continue without the
 *                                  requested groups (the agent may still
 *                                  satisfy the goal).
 *   - **Deny + stop**            — abort the turn.
 *
 * The card never renders a fifth "?" option; the loop's three-tier
 * elevation taxonomy maps every group to one of green-auto /
 * yellow-confirm / red-blocked. This card is the yellow-confirm UI.
 */

import { Check, X } from "lucide-react";

import type { CapabilityRequestSnapshot } from "../lib/chat-state.js";

export type CapabilityDecision = "enable_turn" | "enable_session" | "deny_continue" | "deny_stop";

interface Props {
  /** Snapshot from the pending `capability_requested` event. */
  request?: CapabilityRequestSnapshot;
  /**
   * Called when the user clicks. The host wires the decision back into
   * the in-flight loop (POST resume) and clears the request snapshot
   * on the message so the card unmounts.
   */
  onDecide?(decision: CapabilityDecision, groups: string[]): void;
}

const ACTIONS: { id: CapabilityDecision; label: string; primary?: boolean; deny?: boolean }[] = [
  { id: "enable_turn", label: "Enable for this turn", primary: true },
  { id: "enable_session", label: "Enable for session", primary: true },
  { id: "deny_continue", label: "Deny + continue", deny: true },
  { id: "deny_stop", label: "Deny + stop", deny: true },
];

export function CapabilityApproval({ request, onDecide }: Props) {
  if (!request) return null;
  const { requested_groups, justification, iteration } = request;

  return (
    <div className="my-3 rounded-md border border-warn/40 bg-warn/5 p-3 text-sm">
      <header className="mb-2 flex items-center gap-1.5">
        <span className="font-semibold text-foreground">Capability requested</span>
        <span className="text-xs text-muted-foreground">iteration {iteration}</span>
      </header>
      <p className="mb-2 text-muted-foreground">{justification}</p>
      <p className="mb-3 text-foreground">
        <span className="font-medium">Group{requested_groups.length > 1 ? "s" : ""}: </span>
        <span>{requested_groups.join(", ")}</span>
      </p>
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map((a) => {
          const isPrimary = a.primary;
          const isDeny = a.deny;
          const Icon = isDeny ? X : Check;
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => onDecide?.(a.id, requested_groups)}
              className={[
                "inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium",
                "border transition-colors",
                isPrimary
                  ? "border-accent bg-accent/10 text-accent hover:bg-accent/20"
                  : isDeny
                    ? "border-border bg-background text-muted-foreground hover:bg-muted"
                    : "border-border bg-background hover:bg-muted",
              ].join(" ")}
              disabled={!onDecide}
            >
              <Icon className="h-3 w-3" />
              {a.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
