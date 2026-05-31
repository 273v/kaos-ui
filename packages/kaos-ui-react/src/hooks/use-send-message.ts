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
 *
 * SSE-resume (Stage 1, 2026-05-19): when `opts.resumeFrom` is set, the
 * hook also opens `GET /sessions/{id}/runs/{run_id}/events` and feeds
 * its replayed events through the same `applyEvent` reducer as the
 * live POST path. The reducer is already pure — that's the
 * load-bearing invariant that makes replay-then-live equivalence
 * cheap. See `packages/kaos-ui-react/src/lib/event-handler.ts` and
 * `event-handler.replay.test.ts` (split-then-rejoin property).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyEvent,
  clearCapabilityRequest,
  initialState,
  markAborted,
  pushUserAndAssistantPlaceholder,
  reconcileServerHistory,
  type TranscriptState,
  truncateFrom,
} from "../lib/event-handler.js";
import type { KaosAgentEvent } from "../lib/events.js";
import { readSseStream } from "../lib/streaming.js";
import { joinUrl, type Transport, useTransport } from "../lib/transport.js";

export interface UseSendMessageOptions {
  sessionId: string;
  /** Seed the transcript with prior history on mount / hydration. */
  initialMessages?: TranscriptState["messages"];
  /**
   * When non-null on mount (or when the value transitions from
   * `null` → run id), open the SSE resume endpoint for that run and
   * feed its replayed events through the same reducer as the live
   * POST path.
   *
   * Driven by the route's `useActiveRun(sessionId)` query: pass
   * `{ runId: pointer.run_id }` when `pointer.status === "running"`,
   * `null` otherwise. The hook ignores stale `resumeFrom` values
   * once a live `send()` is already in flight.
   */
  resumeFrom?: { runId: string } | null;
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
  /**
   * Clear the `capability_request` snapshot on a specific message
   * so its CapabilityApproval card unmounts. Called by the host
   * route's `onCapabilityDecide` after the user resolves an
   * elevation prompt (enable_turn / enable_session / deny_continue /
   * deny_stop).
   */
  clearCapability: (messageId: string) => void;
  /**
   * Drop the given message and every row after it from the local
   * transcript. Used by edit-prior / regenerate so the
   * single-source-of-truth reducer truncates in step with the backend's
   * SessionMemory rewind — without a destructive history-refetch-replace
   * (which is what made follow-up sends "flash and disappear"). Call
   * before re-sending the edited / regenerated message.
   */
  truncate: (messageId: string) => void;
  rawEvents: DebugEvent[];
}

/**
 * Dispatch a single SSE frame's payload through the reducer + debug
 * buffer. Shared between the live POST path and the resume GET path
 * so they stay byte-compatible.
 *
 * Returns the parsed Last-Event-ID for the frame (or `null` when the
 * frame had no id), so the resume path can stash it for a future
 * `Last-Event-ID` reconnect.
 */
function dispatchSseFrame(
  evt: { data: unknown; id?: string },
  applyState: (updater: (prev: TranscriptState) => TranscriptState) => void,
  appendDebug: (id: number, event: KaosAgentEvent) => void,
  counterRef: { current: number },
): string | null {
  if (typeof evt.data !== "object" || evt.data === null) return evt.id ?? null;
  const wire = evt.data as { type?: string };
  if (!wire.type) return evt.id ?? null;
  // SPA-emitted SSE-resume envelopes (Stage 1) carry no transcript
  // state. Skip them so they don't reach `applyEvent`'s exhaustive
  // default branch.
  //   - `run_started`             → leading envelope, carries run_id
  //   - `run_resumed_replay_done` → trailing terminator on a resume
  //                                 stream (Stage 2 uses this to tell
  //                                 live tail from replay)
  if (wire.type === "run_started" || wire.type === "run_resumed_replay_done") {
    return evt.id ?? null;
  }
  const ev = wire as KaosAgentEvent;
  counterRef.current += 1;
  appendDebug(counterRef.current, ev);
  applyState((prev) => applyEvent(prev, ev));
  return evt.id ?? null;
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
  // Follow-up sends issued while a stream/resume is in flight are
  // QUEUED here and flushed when the in-flight turn settles — never
  // dropped. This replaces the old `pendingKindRef` + `setTimeout(0)`
  // resume-preemption dance (tasks #459/#351): with the backend now
  // releasing the session lock at stream-end (not after persist), a
  // queued follow-up runs the instant the current turn ends, with no
  // 409 and no silent "I typed and nothing happened" drop.
  const sendQueueRef = useRef<string[]>([]);
  // Always-latest `send`, so the stream `finally` can flush the queue
  // without capturing a stale closure.
  const sendRef = useRef<((message: string) => Promise<void>) | null>(null);
  const flushQueue = useCallback(() => {
    const next = sendQueueRef.current.shift();
    if (next !== undefined) void sendRef.current?.(next);
  }, []);
  // Last sessionId we hydrated against. Lets the reset effect tell
  // "background history refetch for the same session" (don't reset
  // mid-stream) apart from "user navigated to a different session"
  // (MUST reset + abort even if a stream is in flight).
  //
  // Post-0.1.0a3 audit: skipping reset whenever `pending=true` leaked
  // session A's stream + transcript into the session-B view when the
  // user clicked another sidebar entry mid-stream.
  const lastSessionIdRef = useRef<string | null>(null);
  // Tracks the run id we're currently attached to (whether by live
  // send or resume). Used so the resume effect can short-circuit on a
  // duplicate value — TanStack Query's `useActiveRun` re-renders on
  // refetch, and we mustn't reopen the stream every time.
  const attachedRunIdRef = useRef<string | null>(null);
  // Last Last-Event-ID we saw on the resume stream. Reserved for
  // Stage-2 reconnect-on-network-error; the property is stashed today
  // so the wire surface is stable.
  const lastEventIdRef = useRef<string | null>(null);

  const appendDebug = useCallback((id: number, event: KaosAgentEvent) => {
    setRawEvents((prev) => [...prev, { _id: id, event }]);
  }, []);

  // Reset + hydrate on session switch OR when prior-messages refresh.
  // We deliberately depend on both `sessionId` and `initialMessages`:
  // a session switch must always reset, AND an updated history-cache
  // result for the same session should hydrate.
  //
  // FIX-9: skip the reset when an SSE stream is already in flight FOR
  // THE SAME SESSION. The example refetches history on window focus,
  // which would otherwise abort the live turn mid-stream when the
  // user tabs away + back. The session-change branch below ALWAYS
  // tears down the stream — staying in lane on the OLD session would
  // leak its transcript into the new one.
  useEffect(() => {
    const sessionChanged = lastSessionIdRef.current !== opts.sessionId;
    if (sessionChanged) {
      // Navigation to a DIFFERENT session: hard reset + tear down any
      // in-flight stream (staying in lane on the old session would leak
      // its transcript into the new one). This is the ONLY path allowed
      // to discard transcript state.
      abortRef.current?.abort();
      setRawEvents([]);
      eventCounter.current = 0;
      pendingRef.current = false;
      sendQueueRef.current = [];
      attachedRunIdRef.current = null;
      lastEventIdRef.current = null;
      lastSessionIdRef.current = opts.sessionId;
      setState(
        opts.initialMessages && opts.initialMessages.length > 0
          ? { ...initialState, messages: opts.initialMessages }
          : initialState,
      );
      return;
    }
    // SAME session, new `initialMessages` reference = a background
    // history refetch (turn-completion invalidate, the +1200ms title
    // re-invalidate, window-focus, etc.). RECONCILE it into the reducer
    // — never reset. This is the core client-side fix for the "flash and
    // disappear" follow-up bug: a refetch can only fill in
    // server-confirmed rows; it can NEVER delete an optimistic,
    // streaming, or terminal-error row. Safe even mid-stream — the
    // streaming assistant row is a live row and is preserved, so we no
    // longer need the old "skip reset while pending" special-case (which
    // also meant a focus-refetch mid-stream silently dropped the
    // server's settled prefix).
    if (opts.initialMessages && opts.initialMessages.length > 0) {
      setState((prev) => reconcileServerHistory(prev, opts.initialMessages ?? []));
    }
  }, [opts.sessionId, opts.initialMessages]);

  /**
   * Internal — open the resume endpoint as a GET SSE stream and feed
   * events through the shared dispatcher. Stage 1 closes when the
   * server emits `run_resumed_replay_done` (or EOFs on its own); the
   * server's poll-and-tail behavior is Stage 2.
   */
  const _resumeRun = useCallback(
    async (runId: string) => {
      if (pendingRef.current) {
        // A live send() is already running and will populate the
        // transcript; the resume stream would double-apply events.
        return;
      }
      pendingRef.current = true;
      // The resume stream paints into the same placeholder shape the
      // live path uses, so the streaming-assistant message has to
      // exist before the first text_delta arrives. We don't know the
      // user's original message here (the backend can't tell us
      // either; the user message lives in kaos-agents memory). Seed
      // the placeholder with an empty user bubble — the transcript
      // refetch on resume completion will replace it with the real
      // memory snapshot.
      setState((prev) => pushUserAndAssistantPlaceholder(prev, "").state);

      const controller = new AbortController();
      abortRef.current = controller;
      const url = joinUrl(
        transport,
        `/sessions/${encodeURIComponent(opts.sessionId)}/runs/${encodeURIComponent(runId)}/events`,
      );
      const token = transport.getToken?.();
      // Stash the run id so we don't reopen on the next render.
      attachedRunIdRef.current = runId;

      try {
        const handle = await readSseStream(url, {
          method: "GET",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
          fetch: transport.fetch,
        });
        for await (const evt of handle.events) {
          const lastId = dispatchSseFrame(
            evt,
            (updater) => setState(updater),
            appendDebug,
            eventCounter,
          );
          if (lastId !== null) lastEventIdRef.current = lastId;
        }
      } catch (err) {
        // Resume errors are noisier than live errors — the user might
        // have navigated back to a session whose run already
        // completed and was garbage-collected. Map AbortError to a
        // silent reset; everything else lands as a `run_error`
        // synthetic event so the existing reducer renders a banner.
        if ((err as Error)?.name === "AbortError") {
          setState((prev) => markAborted(prev));
        } else {
          setState((prev) =>
            applyEvent(prev, {
              type: "run_error",
              what: (err as Error).message ?? "Resume failed.",
              how_to_fix:
                "The run may have completed or expired; reload the conversation to refresh the transcript.",
            }),
          );
        }
      } finally {
        pendingRef.current = false;
        // Flush any follow-up the user queued while the resume ran.
        flushQueue();
      }
    },
    [opts.sessionId, transport, appendDebug, flushQueue],
  );

  // Open the resume stream when `resumeFrom` is set on mount or
  // changes from `null` → run id. The effect is gated by
  // `attachedRunIdRef` so a TanStack-Query refetch of `useActiveRun`
  // (which returns a stable run id) doesn't reopen the stream.
  useEffect(() => {
    const runId = opts.resumeFrom?.runId ?? null;
    if (!runId) return;
    if (attachedRunIdRef.current === runId) return;
    // Don't fire while the reset effect above hasn't caught up to a
    // session switch — pendingRef.current=true means a live send is
    // mid-flight, and the reset effect would have nulled the resume
    // marker.
    if (pendingRef.current) return;
    void _resumeRun(runId);
  }, [opts.resumeFrom?.runId, _resumeRun]);

  const send = useCallback(
    async (message: string) => {
      if (pendingRef.current) {
        // A stream (live send OR resume) is in flight. QUEUE the
        // follow-up instead of dropping it; it flushes the instant the
        // current turn settles (see `flushQueue` in the stream
        // `finally`). With the backend releasing the session lock at
        // stream-end, the flushed send finds the lock free — no 409,
        // no silent drop. This replaces the old resume-preemption dance.
        sendQueueRef.current.push(message);
        return;
      }
      pendingRef.current = true;
      // Stable per-send correlation/idempotency key. The optimistic
      // user row + assistant placeholder carry it so a racing history
      // refetch can reconcile (fill-in), never delete, this turn's rows.
      const clientKey =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `ck-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      const controller = new AbortController();
      abortRef.current = controller;

      // Optimistic push (tagged origin:"optimistic" + clientKey).
      setState((prev) => pushUserAndAssistantPlaceholder(prev, message, clientKey).state);

      const url = joinUrl(transport, `/sessions/${encodeURIComponent(opts.sessionId)}/messages`);
      const token = transport.getToken?.();

      try {
        const handle = await readSseStream(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            // Idempotency key (Stripe-style): lets the backend dedupe a
            // retried/double-fired POST onto the same run instead of
            // starting a second one. Harmless if the server ignores it.
            "X-Idempotency-Key": clientKey,
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ message }),
          signal: controller.signal,
          // FIX-9: thread the transport's fetch override so msw /
          // retry wrappers / instrumented fetches see the SSE
          // request too. Falls back to global fetch inside readSseStream
          // when transport.fetch isn't provided.
          fetch: transport.fetch,
        });
        if (handle.runId) attachedRunIdRef.current = handle.runId;
        for await (const evt of handle.events) {
          const lastId = dispatchSseFrame(
            evt,
            (updater) => setState(updater),
            appendDebug,
            eventCounter,
          );
          if (lastId !== null) lastEventIdRef.current = lastId;
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
        // Flush a queued follow-up (if any) now that the lock is free.
        flushQueue();
      }
    },
    [opts.sessionId, transport, appendDebug, flushQueue],
  );

  // Keep `sendRef` pointed at the latest `send` so `flushQueue` (called
  // from a stream `finally`) never invokes a stale closure.
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clearCapability = useCallback((messageId: string) => {
    setState((prev) => clearCapabilityRequest(prev, messageId));
  }, []);

  const truncate = useCallback((messageId: string) => {
    setState((prev) => truncateFrom(prev, messageId));
  }, []);

  return { state, send, abort, clearCapability, truncate, rawEvents };
}

// Silence the unused-import warning on `Transport` — it's exported
// only because the same file imports `transport`/`joinUrl`. ty/biome
// keep the import for type-checking even when not referenced.
export type { Transport };
