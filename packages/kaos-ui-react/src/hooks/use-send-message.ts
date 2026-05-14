/**
 * SSE send-message hook. Owns the AbortController + the SSE async-iterator
 * + the TranscriptState reducer wired into React state.
 *
 * Resolves backend URL + auth via the nearest <KaosUIProvider>. Sends:
 *
 *     POST {baseUrl}/sessions/{id}/messages
 *     body: { message }
 *
 * Re-uses the kaos-agents SSE wire shape (each event payload's `type`
 * field discriminates the 15 KaosAgentEvent variants).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type TranscriptState,
  applyEvent,
  initialState,
  markAborted,
  pushUserAndAssistantPlaceholder,
} from "../lib/event-handler.js";
import type { KaosAgentEvent } from "../lib/events.js";
import { readSseStream } from "../lib/streaming.js";
import { joinUrl, useTransport } from "../lib/transport.js";

export interface UseSendMessageOptions {
  sessionId: string;
  /** Seed the transcript with prior history on mount / hydration. */
  initialMessages?: TranscriptState["messages"];
}

/** Wrapper used by the debug overlay — stable per-event id. */
export interface DebugEvent {
  _id: number;
  event: KaosAgentEvent;
}

export interface UseSendMessageResult {
  state: TranscriptState;
  send: (message: string) => Promise<void>;
  abort: () => void;
  rawEvents: DebugEvent[];
}

export function useSendMessage(opts: UseSendMessageOptions): UseSendMessageResult {
  const transport = useTransport();
  const [state, setState] = useState<TranscriptState>(() =>
    opts.initialMessages ? { ...initialState, messages: opts.initialMessages } : initialState,
  );
  const [rawEvents, setRawEvents] = useState<DebugEvent[]>([]);
  const eventCounter = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  // pendingRef mirrors state.pending so the send() gate reads the live
  // value, not a stale closure. Without it, two rapid submits both see
  // state.pending=false at function-close time and both kick off SSE.
  const pendingRef = useRef(false);

  // Reset + hydrate on session switch OR when prior-messages refresh.
  // We deliberately depend on both `sessionId` and `initialMessages`:
  // a session switch must always reset, AND an updated history-cache
  // result for the same session should hydrate.
  //
  // FIX-9: skip the reset when an SSE stream is already in flight.
  // The example refetches history on window focus, which would
  // otherwise abort the live turn mid-stream when the user
  // tabs away + back. We track the live state via pendingRef
  // (which mirrors state.pending) so the effect can no-op cleanly.
  // biome-ignore lint/correctness/useExhaustiveDependencies: sessionId is deliberately a dep — initialMessages reference may be cache-stable across a session switch, so we MUST also reset on id change.
  useEffect(() => {
    if (pendingRef.current) {
      // A stream is mid-flight. Don't tear it down just because the
      // background history query refreshed. The next idle render
      // (after the turn completes) will pick up any genuine
      // initialMessages change via the followup setState below if
      // we still need it.
      return;
    }
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

      const url = joinUrl(transport, `/sessions/${encodeURIComponent(opts.sessionId)}/messages`);
      const token = transport.getToken?.();

      try {
        for await (const evt of readSseStream(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ message }),
          signal: controller.signal,
          // FIX-9: thread the transport's fetch override so msw /
          // retry wrappers / instrumented fetches see the SSE
          // request too. Falls back to global fetch inside readSseStream
          // when transport.fetch isn't provided.
          fetch: transport.fetch,
        })) {
          if (typeof evt.data !== "object" || evt.data === null) continue;
          const wire = evt.data as Partial<KaosAgentEvent> & { type?: string };
          if (!wire.type) continue;
          const ev = wire as KaosAgentEvent;
          eventCounter.current += 1;
          const id = eventCounter.current;
          setRawEvents((prev) => [...prev, { _id: id, event: ev }]);
          setState((prev) => applyEvent(prev, ev));
        }
      } catch (err) {
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
      }
    },
    [opts.sessionId, transport],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { state, send, abort, rawEvents };
}
