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
  type TranscriptState,
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
  // pendingKindRef distinguishes WHO set ``pendingRef=true``. A live
  // ``send()`` is "send"; a background ``_resumeRun()`` is "resume".
  // When the user actively submits a new message and a resume happens
  // to be in flight, the resume stream may be hung waiting for a close
  // frame the server never sends. Without this distinction the send
  // would silently exit at the ``if (pendingRef.current) return``
  // gate, producing the "I typed and nothing happened" failure mode
  // (tasks #459 / #351, reproduced 6 times in the 2026-05-19 session).
  // With this distinction, send() preempts an in-flight resume.
  const pendingKindRef = useRef<"send" | "resume" | null>(null);
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
    if (pendingRef.current && !sessionChanged) {
      // Same-session refetch while streaming — leave the SSE alone.
      return;
    }
    // Session changed OR no stream in flight → tear down + hydrate.
    abortRef.current?.abort();
    setRawEvents([]);
    eventCounter.current = 0;
    pendingRef.current = false;
    // P0 — keep `attachedRunIdRef` populated across same-session
    // history refetches. The reference is consulted by the
    // `_resumeRun` useEffect to decide whether a freshly-discovered
    // `resumeFrom.runId` belongs to a run THIS hook instance already
    // attached to. Pre-fix this got nulled on every same-session
    // history refetch (which happens on turn completion), so the
    // next `useActiveRun` poll — if it returned the just-finished
    // run's pointer with stale `status="running"` because the
    // BackgroundTask hadn't flipped it yet — would re-fire
    // `_resumeRun`, set `pendingRef=true`, and silently block the
    // user's next `send()` for ~100-500ms. The classic "I typed,
    // textarea cleared, nothing happened" follow-up regression.
    // Only null this when the session actually changes.
    if (sessionChanged) {
      attachedRunIdRef.current = null;
      lastEventIdRef.current = null;
    }
    lastSessionIdRef.current = opts.sessionId;
    if (opts.initialMessages && opts.initialMessages.length > 0) {
      setState({ ...initialState, messages: opts.initialMessages });
    } else {
      setState(initialState);
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
      pendingKindRef.current = "resume";
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
        if (pendingKindRef.current === "resume") {
          pendingKindRef.current = null;
        }
      }
    },
    [opts.sessionId, transport, appendDebug],
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
        // Preempt a hung resume — user intent supersedes a background
        // SSE that may be stuck waiting for a close frame the server
        // never emitted. Without this, the "I typed `sure` and nothing
        // happened" failure mode silently drops the user's send (tasks
        // #459 / #351). Aborting the resume stream triggers its catch
        // + finally clause, which flips ``pendingRef`` back to false
        // and clears the ``"resume"`` kind. The await-microtask gives
        // the finally clause a tick to run before we re-check.
        if (pendingKindRef.current === "resume") {
          abortRef.current?.abort();
          await new Promise<void>((resolve) => {
            setTimeout(resolve, 0);
          });
        }
        if (pendingRef.current) return;
      }
      pendingRef.current = true;
      pendingKindRef.current = "send";
      const controller = new AbortController();
      abortRef.current = controller;

      // Optimistic push.
      setState((prev) => pushUserAndAssistantPlaceholder(prev, message).state);

      const url = joinUrl(transport, `/sessions/${encodeURIComponent(opts.sessionId)}/messages`);
      const token = transport.getToken?.();

      try {
        const handle = await readSseStream(url, {
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
        if (pendingKindRef.current === "send") {
          pendingKindRef.current = null;
        }
      }
    },
    [opts.sessionId, transport, appendDebug],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clearCapability = useCallback((messageId: string) => {
    setState((prev) => clearCapabilityRequest(prev, messageId));
  }, []);

  return { state, send, abort, clearCapability, rawEvents };
}

// Silence the unused-import warning on `Transport` — it's exported
// only because the same file imports `transport`/`joinUrl`. ty/biome
// keep the import for type-checking even when not referenced.
export type { Transport };
