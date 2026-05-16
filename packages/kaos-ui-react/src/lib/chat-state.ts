/**
 * In-memory chat state shape used by `useSendMessage` + transcript views.
 *
 * Decoupled from any specific persistence layer — consuming apps may
 * mirror this into TanStack Query cache or Zustand, but the streaming
 * hook itself owns a React-state-backed transcript.
 */

export type MessageRole = "user" | "assistant" | "tool" | "error" | "system";

export interface ToolCallSummary {
  id: string;
  name: string;
  status: "running" | "done" | "error";
  args_preview?: string;
  result_preview?: string;
}

/**
 * Per-turn tool-policy snapshot (TR-7 / TR-9).
 *
 * Populated when the backend emits `tool_policy_decided`. Surfaced on
 * the assistant message as a transparency badge so the user can see
 * which tool categories were active for this specific turn.
 */
export interface ToolPolicySnapshot {
  turn_groups: string[];
  ceiling_groups: string[];
  reasoning: string;
  confidence: number;
  fell_back_to_ceiling: boolean;
  cost_usd: number;
  latency_ms: number;
}

/**
 * AgenticLoop auto-elevation snapshot.
 *
 * Populated when the loop emitted at least one `tool_policy_elevated`
 * event during this turn. Drives the inline "Auto-enabled X" badge
 * + "Pin to session" affordance.
 */
export interface ElevationSnapshot {
  elevated_groups: string[];
  kept_groups: string[];
  previous_allowed: string[];
  rationale: string;
  iteration: number;
}

/**
 * Critic verdict snapshot (drives GoalCheckBadge color).
 */
export interface GoalCheckSnapshot {
  kind: "satisfied" | "needs_more_work" | "insufficient_evidence";
  rationale: string;
  next_action: string;
  missing: string;
  confidence: number;
  iteration: number;
  cost_usd: number;
  latency_ms: number;
}

/**
 * AgenticLoop termination snapshot — always set on the assistant
 * message after a turn completes. The SPA renders a terminal banner
 * for non-"satisfied" reasons.
 */
export interface LoopTerminationSnapshot {
  reason:
    | "satisfied"
    | "insufficient_evidence"
    | "max_iterations"
    | "cost_exceeded"
    | "wall_clock_exceeded"
    | "stuck_no_progress"
    | "user_interrupt";
  iterations_used: number;
  elevations_used: number;
  cost_usd: number;
  wall_clock_ms: number;
}

/**
 * Yellow-confirm capability request — pending user approval.
 *
 * When present on a ChatMessage, the SPA renders the CapabilityApproval
 * inline card with four actions. The component is responsible for
 * clearing this field after the user decides.
 */
export interface CapabilityRequestSnapshot {
  requested_groups: string[];
  justification: string;
  iteration: number;
  previous_allowed: string[];
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  /** Markdown source; rendered via the package's `<MessageMarkdown>`. */
  content: string;
  created_at: number;
  /** True while text_delta events are still accumulating for this message. */
  streaming: boolean;
  /**
   * Wall-clock ms when the turn STARTED — set when the assistant
   * placeholder is created. `latency_ms` is `Date.now() - started_at`
   * at turn-complete time.
   */
  started_at?: number;
  /** Aggregated per-turn usage; populated on `turn_summary`. */
  tokens?: number;
  /** Sum of input tokens across all LLM calls in this turn. */
  input_tokens?: number;
  /** Sum of output tokens across all LLM calls in this turn. */
  output_tokens?: number;
  cost_usd?: number;
  /** Wall-clock duration of the turn in ms — set on turn complete / error. */
  latency_ms?: number;
  /** Inline tool-call cards rendered inside the assistant message. */
  tool_calls?: ToolCallSummary[];
  /**
   * Per-turn tool-policy decision the planner made for this turn.
   * Optional — set only when the backend emits `tool_policy_decided`
   * (kaos-ui example extension, TR-7).
   */
  tool_policy?: ToolPolicySnapshot;
  /**
   * AgenticLoop auto-elevations applied during this turn (kaos-agents
   * 0.1.0a4). Each entry corresponds to one `tool_policy_elevated`
   * event — multiple iterations can each elevate.
   */
  elevations?: ElevationSnapshot[];
  /**
   * Last Critic verdict from this turn. The most recent
   * `goal_checked` wins (replan iterations overwrite).
   */
  goal_check?: GoalCheckSnapshot;
  /**
   * Set when the loop terminates. The SPA renders a LoopTerminatedBanner
   * for any non-"satisfied" reason.
   */
  loop_termination?: LoopTerminationSnapshot;
  /**
   * Pending capability request awaiting user approval. Cleared by the
   * CapabilityApproval card after the user clicks.
   */
  capability_request?: CapabilityRequestSnapshot;
}

export type TurnStatusKind =
  | { kind: "idle" }
  | { kind: "thinking" }
  | { kind: "tool"; tool: string }
  | { kind: "step"; index: number }
  | { kind: "error"; what: string };

/**
 * Stable-ish message id for transcript entries. Time-prefixed so a
 * sort by `id` matches arrival order; random suffix avoids collisions
 * for messages dispatched in the same millisecond.
 */
export function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
