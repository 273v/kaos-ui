// SSE send-message hook. Owns the AbortController + the SSE async-iterator
// + the TranscriptState reducer wired into React state.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { loadToken } from "@/auth/storage";
import {
  applyEvent,
  initialState,
  markAborted,
  pushUserAndAssistantPlaceholder,
  type TranscriptState,
} from "@/lib/event-handler";
import type { KaosAgentEvent, MemoryEventEvent } from "@/lib/events";
import { queryKeys } from "@/lib/query-keys";
import { readSseStream } from "@/lib/streaming";

export interface UseSendMessageOptions {
  sessionId: string;
  /** Seed the transcript with prior history on mount / hydration. */
  initialMessages?: TranscriptState["messages"];
}

/** Wrapper used by the debug overlay — stable `_id` per appended event. */
export interface DebugEvent {
  _id: number;
  event: KaosAgentEvent;
}

export function useSendMessage(opts: UseSendMessageOptions) {
  const [state, setState] = useState<TranscriptState>(() =>
    opts.initialMessages ? { ...initialState, messages: opts.initialMessages } : initialState,
  );
  const [rawEvents, setRawEvents] = useState<DebugEvent[]>([]);
  const eventCounter = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  // MEDIUM #5 — pendingRef mirrors state.pending so the send() gate
  // reads the live value, not a stale closure. Pre-fix, two rapid
  // submits both saw state.pending=false at function-close time and
  // both kicked off SSE streams, with the second abort marking the
  // first stream's assistant placeholder as "stopped."
  const pendingRef = useRef(false);
  const qc = useQueryClient();

  // Reset + hydrate on session switch OR when the prior-messages query
  // resolves. Single effect to avoid the stale-cache trap: if A's
  // history is cached, navigating B→A keeps the `initialMessages`
  // reference stable, so a dep-on-initialMessages effect would NOT
  // refire on the session switch. By depending on both, we always
  // reset and rehydrate from whatever cache TanStack Query has.
  // biome-ignore lint/correctness/useExhaustiveDependencies: sessionId is deliberately a dep — initialMessages reference may be cache-stable across a session switch, so we MUST also reset on id change.
  useEffect(() => {
    abortRef.current?.abort();
    setRawEvents([]);
    eventCounter.current = 0;
    pendingRef.current = false;
    if (opts.initialMessages && opts.initialMessages.length > 0) {
      setState({ ...initialState, messages: opts.initialMessages });
    } else {
      setState(initialState);
    }
  }, [opts.sessionId, opts.initialMessages]);

  const send = useCallback(
    async (message: string) => {
      if (pendingRef.current) return;
      pendingRef.current = true;
      const controller = new AbortController();
      abortRef.current = controller;

      // Optimistic push.
      setState((prev) => pushUserAndAssistantPlaceholder(prev, message).state);

      const token = loadToken();
      const url = `/v1/chat/sessions/${encodeURIComponent(opts.sessionId)}/messages`;

      try {
        for await (const evt of readSseStream(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ message }),
          signal: controller.signal,
        })) {
          if (typeof evt.data !== "object" || evt.data === null) continue;
          const wire = evt.data as Partial<KaosAgentEvent> & { type?: string };
          if (!wire.type) continue;
          const ev = wire as KaosAgentEvent;
          eventCounter.current += 1;
          const id = eventCounter.current;
          setRawEvents((prev) => [...prev, { _id: id, event: ev }]);
          setState((prev) => applyEvent(prev, ev));

          // Side effect: invalidate the session list cache when the
          // agent persists state (bumps message_count + title).
          if (wire.type === "memory_event") {
            const mem = wire as MemoryEventEvent;
            if (mem.kind === "persisted") {
              qc.invalidateQueries({ queryKey: queryKeys.sessions() });
            }
          }
        }
      } catch (err) {
        // MEDIUM #4 — reader errors (server disconnect, network drop)
        // are now re-thrown by readSseStream so we catch them here and
        // ALWAYS finalize the streaming placeholder. Pre-fix, errors
        // were swallowed and the placeholder stayed in `streaming=true`
        // forever ("Thinking…" spinner of doom).
        if ((err as Error)?.name === "AbortError") {
          setState((prev) => markAborted(prev));
        } else {
          setState((prev) =>
            applyEvent(prev, {
              type: "run_error",
              what: (err as Error).message ?? "Stream failed.",
              how_to_fix: "Check that the backend is reachable; reload the page if it's stuck.",
            }),
          );
        }
      } finally {
        pendingRef.current = false;
        // After the stream closes (or errors), refresh session metadata.
        qc.invalidateQueries({ queryKey: queryKeys.session(opts.sessionId) });
        qc.invalidateQueries({ queryKey: queryKeys.sessions() });
      }
    },
    [opts.sessionId, qc],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { state, send, abort, rawEvents };
}
