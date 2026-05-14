/**
 * Per-session citations state + post-turn extraction (P2-1).
 *
 * Wire constraint (kaos-agents 0.1.0a1): `attributes.result_summary`
 * on `tool_call/complete` SSE events is truncated to 200 chars
 * (`kaos_agents/patterns/chat.py:295`). So we can't tap the wire for
 * structured citation arrays. Instead we run extraction on the
 * assistant's final response text via the backend after each turn.
 *
 * State lives in this hook (not TanStack Query cache) so we can
 * accumulate across turns and update live without round-tripping a
 * per-message query key.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/chat-state";
import { type Citation, extractCitations } from "@/lib/citations";

export interface UseCitationsResult {
  /** Citations grouped by assistant message id, in arrival order. */
  byMessage: Map<string, Citation[]>;
  /** Total citation count across the session. */
  total: number;
  /** Last extraction error message, if any. */
  error: string | null;
  /** True while an extraction is in flight. */
  pending: boolean;
}

/**
 * Watches `messages` for completed assistant turns and extracts
 * citations from each one exactly once. The `extracted` ref keeps
 * us from re-firing when the same message lands again (e.g., after
 * history hydration).
 */
export function useCitations(
  sessionId: string | null,
  messages: ChatMessage[],
): UseCitationsResult {
  const [byMessage, setByMessage] = useState<Map<string, Citation[]>>(() => new Map());
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const extracted = useRef<Set<string>>(new Set());
  const lastSessionId = useRef<string | null>(null);

  // Reset on session switch — citations are per-session.
  useEffect(() => {
    if (lastSessionId.current === sessionId) return;
    lastSessionId.current = sessionId;
    extracted.current = new Set();
    setByMessage(new Map());
    setError(null);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    // Find assistant messages that are done streaming + have content
    // we haven't extracted yet.
    const pendingExtractions = messages.filter(
      (m) =>
        m.role === "assistant" &&
        !m.streaming &&
        m.content.length > 0 &&
        !extracted.current.has(m.id),
    );
    if (pendingExtractions.length === 0) return;

    let cancelled = false;
    setPending(true);

    Promise.all(
      pendingExtractions.map(async (m) => {
        // Optimistically mark as extracted so we don't re-fire on the
        // next render cycle if `messages` reference changes.
        extracted.current.add(m.id);
        try {
          const resp = await extractCitations(sessionId, m.content);
          return [m.id, resp.citations] as const;
        } catch (err) {
          // Keep the message marked as extracted to avoid hammering
          // the endpoint with a known-failing text. Surface the error
          // to the panel header.
          if (!cancelled) {
            const what =
              typeof err === "object" && err !== null && "what" in err
                ? String((err as { what: unknown }).what)
                : (err as Error)?.message || "Citation extraction failed.";
            setError(what);
          }
          return null;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      setByMessage((prev) => {
        const next = new Map(prev);
        for (const r of results) {
          if (!r) continue;
          const [mid, cites] = r;
          if (cites.length > 0) next.set(mid, cites);
        }
        return next;
      });
      setPending(false);
    });

    return () => {
      cancelled = true;
      setPending(false);
    };
  }, [sessionId, messages]);

  const total = Array.from(byMessage.values()).reduce((acc, arr) => acc + arr.length, 0);
  const reset = useCallback(() => {
    extracted.current = new Set();
    setByMessage(new Map());
    setError(null);
  }, []);
  void reset; // Reserved for future "clear panel" UI; not exposed yet.

  return { byMessage, total, error, pending };
}
