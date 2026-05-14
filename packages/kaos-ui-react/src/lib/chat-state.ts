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
