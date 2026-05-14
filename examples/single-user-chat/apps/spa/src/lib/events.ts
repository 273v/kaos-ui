// Wire-side typed definitions for the 15 kaos-agents event classes.
//
// Verified against `kaos-agents==0.1.0a1` PyPI install. The wire shapes
// are loose by design (event-handler.ts dispatches on `.type`) but
// these aliases make the renderer assertions readable.
//
// Per ARCHITECTURE.md § 5.3 + PATTERNS.md P-015. The `span` event class
// is one wire type with a (subject, phase) discriminator inside.

export type SpanSubject = "turn" | "step" | "tool_call" | "plan" | "subagent" | "handoff";

export type SpanPhase = "start" | "progress" | "complete" | "error" | "cancelled";

export interface SpanEvent {
  type: "span";
  subject: SpanSubject;
  phase: SpanPhase;
  span_id: string;
  parent_span_id: string | null;
  name?: string | null;
  duration_ms?: number | null;
  error_type?: string | null;
  error_message?: string | null;
  attributes: Record<string, unknown>;
}

export interface TextDeltaEvent {
  type: "text_delta";
  content: string;
}
export interface ThinkingDeltaEvent {
  type: "thinking_delta";
  content: string;
}
export interface ToolCallArgsDeltaEvent {
  type: "tool_call_args_delta";
  tool_name?: string;
  call_id?: string;
  delta?: string;
}
export interface IntentClassifiedEvent {
  type: "intent_classified";
  intent: string;
  confidence?: number;
  reasoning?: string;
}
export interface PlanProposedEvent {
  type: "plan_proposed";
  steps?: unknown[];
}
export interface CitationFoundEvent {
  type: "citation_found";
  citation?: Record<string, unknown>;
}
export interface UsageObservedEvent {
  type: "usage_observed";
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  source?: string;
}
export interface EvidenceInsufficientEvent {
  type: "evidence_insufficient";
  reason?: string;
}
export interface GroundingRefusalEvent {
  type: "grounding_refusal_triggered";
  reason?: string;
}
export interface TurnSummaryEvent {
  type: "turn_summary";
  text: string;
  intent?: string;
  tool_calls?: unknown[];
  tokens_used?: number;
  cost_usd?: number;
  input_tokens?: number;
  output_tokens?: number;
}
export interface MemoryEventEvent {
  type: "memory_event";
  kind: "added" | "evicted" | "summarized" | "hydrated" | "persisted" | "searched";
  section?: string;
}
export interface RunErrorEvent {
  type: "run_error";
  what?: string;
  how_to_fix?: string;
  alternative?: string;
}
export interface BudgetExceededEvent {
  type: "budget_exceeded";
  limit_usd?: number;
  spent_usd?: number;
}
export interface ToolCallApprovalRequiredEvent {
  type: "tool_call_approval_required";
  tool_name?: string;
  args?: Record<string, unknown>;
  run_state_ref?: string;
}

export type KaosAgentEvent =
  | SpanEvent
  | TextDeltaEvent
  | ThinkingDeltaEvent
  | ToolCallArgsDeltaEvent
  | IntentClassifiedEvent
  | PlanProposedEvent
  | CitationFoundEvent
  | UsageObservedEvent
  | EvidenceInsufficientEvent
  | GroundingRefusalEvent
  | TurnSummaryEvent
  | MemoryEventEvent
  | RunErrorEvent
  | BudgetExceededEvent
  | ToolCallApprovalRequiredEvent;

/** All 15 event type strings, in canonical order. */
export const ALL_EVENT_TYPES = [
  "span",
  "text_delta",
  "thinking_delta",
  "tool_call_args_delta",
  "intent_classified",
  "plan_proposed",
  "citation_found",
  "usage_observed",
  "evidence_insufficient",
  "grounding_refusal_triggered",
  "turn_summary",
  "memory_event",
  "run_error",
  "budget_exceeded",
  "tool_call_approval_required",
] as const;

export type EventType = (typeof ALL_EVENT_TYPES)[number];
