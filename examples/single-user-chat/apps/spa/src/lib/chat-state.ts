// In-memory chat state shape used by useSendMessage + the chat route.
//
// We don't persist this to TanStack Query cache verbatim; instead the
// hook owns a React-state-backed transcript and only rewrites the
// session-meta cache when stream-level things change (last_message_at).

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
  /** Markdown source; rendered via lib/markdown.ts. */
  content: string;
  created_at: number;
  /** True while text_delta events are still accumulating. */
  streaming: boolean;
  /** Aggregated per-turn usage; populated on `turn_summary`. */
  tokens?: number;
  cost_usd?: number;
  /** Inline tool-call cards rendered inside the assistant message. */
  tool_calls?: ToolCallSummary[];
}

export type TurnStatus =
  | { kind: "idle" }
  | { kind: "thinking" }
  | { kind: "tool"; tool: string }
  | { kind: "step"; index: number }
  | { kind: "error"; what: string };

export function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
