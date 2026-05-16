// Mirrors of the backend's Pydantic shapes in `backend/app/models.py`.
// Phase 2 task #19 replaces this with a generated client from openapi-ts.

export interface ModelEntry {
  id: string;
  label: string;
  provider: "anthropic" | "openai" | "google" | "xai";
  context_window?: number | null;
  recommended_for?: string | null;
}

export interface ModelListResponse {
  models: ModelEntry[];
}

export type Persona = "research" | "drafting" | "forensics";

/**
 * Legacy per-turn ceiling shape (pre-AgenticLoop, TR-3 / kaos-agents
 * 0.1.0a2). Surviving as a back-compat computed_field on
 * :class:`SessionMeta` — derived from ``policy`` at read time. New
 * code should read / write ``policy`` directly.
 */
export interface SessionToolSetWire {
  allowed_groups: string[];
  denied_tools: string[];
  auto_narrow: boolean;
}

/**
 * Two-tier per-session policy (kaos-agents 0.1.0a4 AgenticLoop).
 *
 * Mirror of :class:`backend.app.models.SessionPolicyWire`.
 *
 * - ``allowed_groups`` is the working set the agent sees.
 * - ``soft_ceiling`` is the auto-elevation upper bound — the loop may
 *   silently widen ``allowed_groups`` up to this set when the per-turn
 *   planner reports green-auto ``dropped_groups``.
 * - ``denied_tools`` wins over every allow.
 * - ``persona`` is the named preset, threaded into the planner.
 * - The three independent loop limiters (``max_loop_iterations`` /
 *   ``max_loop_cost_usd`` / ``max_loop_wall_clock_seconds``) cap the
 *   plan-execute-check-replan loop per turn.
 */
export interface SessionPolicyWire {
  allowed_groups: string[];
  soft_ceiling: string[];
  denied_tools: string[];
  persona: Persona;
  auto_narrow: boolean;
  auto_elevate: boolean;
  auto_loop: boolean;
  max_loop_iterations: number;
  max_loop_cost_usd: number;
  max_loop_wall_clock_seconds: number;
}

export interface SessionMeta {
  id: string;
  title: string;
  model: string;
  system_prompt: string;
  /** New canonical shape (kaos-agents 0.1.0a4 AgenticLoop). */
  policy: SessionPolicyWire;
  /**
   * Back-compat computed_field — derived from ``policy.allowed_groups``
   * + ``policy.denied_tools`` + ``policy.auto_narrow``. Drops one
   * release after the SPA cuts over to reading ``policy`` directly.
   */
  tool_set: SessionToolSetWire;
  /** Back-compat — equal to ``!is_blocking_all``. */
  tools_enabled: boolean;
  created_at: string;
  last_message_at: string | null;
  message_count: number;
  archived: boolean;
  starred: boolean;
  title_source: "manual" | "auto";
}

// TR-4: GET /v1/chat/categories row + PATCH .../tool-set body.

export interface CategoryInfo {
  id: string;
  label: string;
  description: string;
  default_enabled: boolean;
  tool_count: number;
}

export interface CategoriesResponse {
  categories: CategoryInfo[];
}

export interface ToolSetUpdateBody {
  allowed_groups?: string[];
  denied_tools?: string[];
  auto_narrow?: boolean;
}

export interface SessionSummary {
  id: string;
  title: string;
  model: string;
  last_message_at: string | null;
  created_at: string;
  message_count: number;
  archived: boolean;
  starred: boolean;
  title_source: "manual" | "auto";
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  next_cursor: string | null;
}

export interface CreateSessionBody {
  title?: string;
  model?: string;
  system_prompt?: string;
  tools_enabled?: boolean;
}

export interface HistoryToolCall {
  id: string;
  name: string;
  status: "running" | "done" | "error";
  args_preview?: string | null;
  result_preview?: string | null;
}

export interface HistoryMessageEntry {
  role: "user" | "assistant" | "system";
  content: string;
  added_at: number;
  tool_calls?: HistoryToolCall[];
}

export interface PatchMetaBody {
  title?: string;
  model?: string;
  system_prompt?: string;
  tools_enabled?: boolean;
  starred?: boolean;
}

// ── AgenticLoop SSE event payloads (kaos-agents 0.1.0a4) ─────────────

export interface ToolPolicyElevatedWire {
  type: "tool_policy_elevated";
  elevated_groups: string[];
  kept_groups: string[];
  previous_allowed: string[];
  rationale: string;
  iteration: number;
}

export interface CapabilityRequestedWire {
  type: "capability_requested";
  requested_groups: string[];
  justification: string;
  iteration: number;
  previous_allowed: string[];
}

export interface GoalCheckedWire {
  type: "goal_checked";
  kind: "satisfied" | "needs_more_work" | "insufficient_evidence";
  rationale: string;
  next_action: string;
  missing: string;
  confidence: number;
  iteration: number;
  cost_usd: number;
  latency_ms: number;
}

export interface LoopTerminatedWire {
  type: "loop_terminated";
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
