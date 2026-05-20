/**
 * TanStack Query hook for the per-session active-run pointer (SSE
 * resume — Stage 1).
 *
 * The backend writes `runs/active.json` for every in-flight chat
 * turn; on session mount the SPA reads it to decide whether to open
 * the resume stream rather than wait for a fresh user message.
 *
 * Returns the parsed pointer, or `null` when no run has ever been
 * recorded for this session. The query is gated by `sessionId` so
 * `useActiveRun(null)` is a no-op.
 */

import { useQuery } from "@tanstack/react-query";

import { kaosQueryKeys } from "../lib/query-keys.js";
import { transportJson, useTransport } from "../lib/transport.js";

/**
 * Wire shape of `GET /v1/chat/sessions/{id}/runs/active`. Matches the
 * Python pointer dict in `app/services/run_log.py:RunEventLog.open`.
 *
 * `last_seq === -1` is a valid pointer — the run was opened but no
 * events have been written yet. `null` is the higher-level "no run"
 * sentinel, returned by `useActiveRun` itself, not as a `status`.
 */
export interface ActiveRunPointer {
  run_id: string;
  session_id: string;
  status: "running" | "done" | "error" | "interrupted";
  started_at: number;
  completed_at: number | null;
  last_seq: number;
  model: string | null;
  turn_index: number | null;
}

/**
 * Read the active-run pointer for a session.
 *
 * - `data === null`            — no run has ever been recorded.
 * - `data.status === "running"` — open the resume stream.
 * - any other status            — fall back to the persisted
 *   transcript (`useSessionMessages`).
 *
 * The query refetches on window focus so a tab that comes back from
 * the background sees the current state. `staleTime` is generous
 * (~5s) so a same-session refetch on every render doesn't hammer the
 * backend.
 */
export function useActiveRun(sessionId: string | null) {
  const transport = useTransport();
  return useQuery<ActiveRunPointer | null>({
    queryKey: kaosQueryKeys.activeRun(sessionId ?? ""),
    queryFn: () =>
      transportJson<ActiveRunPointer | null>(
        transport,
        `/sessions/${encodeURIComponent(sessionId as string)}/runs/active`,
      ),
    enabled: !!sessionId,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
}
