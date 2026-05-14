import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";
import { queryKeys } from "@/lib/query-keys";

export interface HistoryToolCall {
  id: string;
  name: string;
  status: "running" | "done" | "error";
  args_preview?: string | null;
  result_preview?: string | null;
}

export interface HistoryMessage {
  role: "user" | "assistant" | "system";
  content: string;
  added_at: number;
  /** Populated only for assistant turns that ran tools. */
  tool_calls?: HistoryToolCall[];
}

export interface HistoryResponse {
  session_id: string;
  turn_count: number;
  item_count: number;
  messages: HistoryMessage[];
}

/**
 * Loads the prior conversation for a session from
 * `GET /v1/chat/sessions/{id}/messages`. Backed by kaos-agents'
 * SessionMemory MESSAGES section (server-side translation in
 * `app/routers/chat.py`).
 */
export function useSessionMessages(sessionId: string) {
  return useQuery({
    queryKey: [...queryKeys.session(sessionId), "history"] as const,
    queryFn: () =>
      apiJson<HistoryResponse>(`/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`),
    enabled: Boolean(sessionId),
    // Refetch on focus so a session that grew in another tab catches up.
    refetchOnWindowFocus: true,
  });
}
