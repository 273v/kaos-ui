/**
 * TanStack Query keys used by the package's hooks. All keys are
 * namespaced under `@273v/kaos-ui-react` so consumers can use any
 * other key prefix for their own queries without collision.
 *
 * Exported so consumers can invalidate package-owned caches from
 * their own callbacks (e.g., after a session POST that the package
 * doesn't own).
 */

const PREFIX = "@273v/kaos-ui-react";

export const kaosQueryKeys = {
  /** Per-session file list. */
  files: (sessionId: string) => [PREFIX, "session", sessionId, "files"] as const,
  /** Per-session citations cache (currently driven by useCitations React state). */
  citations: (sessionId: string) => [PREFIX, "session", sessionId, "citations"] as const,
  /**
   * Per-session active-run pointer. The SPA polls this on session mount
   * to decide whether to open the SSE resume endpoint instead of waiting
   * for the user to send a new message. See `useActiveRun`.
   */
  activeRun: (sessionId: string) => [PREFIX, "session", sessionId, "activeRun"] as const,
};

export type KaosQueryKey = ReturnType<(typeof kaosQueryKeys)[keyof typeof kaosQueryKeys]>;
