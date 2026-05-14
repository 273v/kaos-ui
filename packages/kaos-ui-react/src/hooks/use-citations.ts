/**
 * Per-session citations state + post-turn extraction.
 *
 * Wire constraint (kaos-agents 0.1.0a1): tool_call/complete events on
 * the SSE wire truncate the result to 200 chars, so we can't tap the
 * stream for structured citation arrays. Instead we run extraction on
 * the assistant's final response text via POST /sessions/{id}/citations
 * after each turn lands. State accumulates across turns in this hook
 * (not TanStack Query cache) so live updates don't depend on a
 * per-message query key.
 */

import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../lib/chat-state.js";
import { type Citation, extractCitations } from "../lib/citations.js";
import { useTransport } from "../lib/transport.js";

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
  const transport = useTransport();
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
          const resp = await extractCitations(transport, sessionId, m.content);
          return [m.id, resp.citations] as const;
        } catch (err) {
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
  }, [sessionId, messages, transport]);

  const total = Array.from(byMessage.values()).reduce((acc, arr) => acc + arr.length, 0);

  return { byMessage, total, error, pending };
}
