// SSE send-message hook. Owns the AbortController + the SSE async-iterator
// + the TranscriptState reducer wired into React state.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

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
  /** Seed the transcript with prior history on first mount. */
  initialMessages?: TranscriptState["messages"];
}

export function useSendMessage(opts: UseSendMessageOptions) {
  const [state, setState] = useState<TranscriptState>(() =>
    opts.initialMessages ? { ...initialState, messages: opts.initialMessages } : initialState,
  );
  const abortRef = useRef<AbortController | null>(null);
  const qc = useQueryClient();

  const send = useCallback(
    async (message: string) => {
      if (state.pending) return;
      abortRef.current?.abort();
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
          setState((prev) => applyEvent(prev, wire as KaosAgentEvent));

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
        if ((err as Error)?.name === "AbortError") {
          setState((prev) => markAborted(prev));
        } else {
          setState((prev) =>
            applyEvent(prev, {
              type: "run_error",
              what: (err as Error).message ?? "Stream failed.",
            }),
          );
        }
      } finally {
        // After the stream closes, refresh session metadata (msg count).
        qc.invalidateQueries({ queryKey: queryKeys.session(opts.sessionId) });
        qc.invalidateQueries({ queryKey: queryKeys.sessions() });
      }
    },
    [opts.sessionId, qc, state.pending],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { state, send, abort };
}
