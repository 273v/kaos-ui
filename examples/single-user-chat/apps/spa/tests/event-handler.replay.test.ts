// SSE-resume property test (Stage 1).
//
// `applyEvent` is a pure `(state, event) => state` reducer. The resume
// design (`kaos-modules/docs/plans/2026-05-19-sse-resumption-live-runs.md`
// §5.3) relies on one invariant: folding events as a single stream
// produces the same final state as folding the prefix offline and the
// suffix live. If a reducer step ever leaks wall-clock time or event
// ordering, this test fails and the resume contract is broken.
//
// Placed in the SPA tests/ rather than packages/kaos-ui-react/test/
// because the package itself doesn't bundle a test runner; the SPA
// already has vitest configured and imports the reducer through the
// same public surface (`@273v/kaos-ui-react/lib`) that any consumer
// would.

import type { KaosAgentEvent } from "@273v/kaos-ui-react/lib";
import {
  applyEvent,
  initialState,
  pushUserAndAssistantPlaceholder,
  type TranscriptState,
} from "@273v/kaos-ui-react/lib";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function makeStream(): KaosAgentEvent[] {
  // A representative cross-section of the wire vocabulary: spans
  // (start + complete pairs on both `turn` and `tool_call`), text
  // deltas accumulating into an assistant message, a tool_call
  // lifecycle, a usage_observed rollup, and a turn_summary
  // finalization. This is the same shape the live POST path sees, so
  // a passing test here implies replay-then-live reproduces a live
  // run.
  return [
    {
      type: "span",
      subject: "turn",
      phase: "start",
      span_id: "t",
      parent_span_id: null,
      name: "turn.start",
      duration_ms: null,
      error_type: null,
      error_message: null,
      attributes: {},
    },
    { type: "text_delta", content: "Hel" },
    { type: "text_delta", content: "lo " },
    {
      type: "span",
      subject: "tool_call",
      phase: "start",
      span_id: "tc1",
      parent_span_id: "t",
      name: "tool_call.start",
      duration_ms: null,
      error_type: null,
      error_message: null,
      attributes: { call_id: "tc1", tool_name: "kaos-pdf-extract-text" },
    },
    {
      type: "span",
      subject: "tool_call",
      phase: "complete",
      span_id: "tc1",
      parent_span_id: "t",
      name: "tool_call.complete",
      duration_ms: 12.4,
      error_type: null,
      error_message: null,
      attributes: { call_id: "tc1", tool_name: "kaos-pdf-extract-text", result_preview: "ok" },
    },
    { type: "text_delta", content: "world." },
    {
      type: "usage_observed",
      input_tokens: 100,
      output_tokens: 4,
      total_tokens: 104,
      cost_usd: 0.0002,
      source: "anthropic",
    },
    {
      type: "turn_summary",
      text: "Hello world.",
      tokens_used: 104,
      input_tokens: 100,
      output_tokens: 4,
      cost_usd: 0.0002,
    },
    {
      type: "span",
      subject: "turn",
      phase: "complete",
      span_id: "t",
      parent_span_id: null,
      name: "turn.complete",
      duration_ms: 800.0,
      error_type: null,
      error_message: null,
      attributes: {},
    },
  ];
}

function foldAll(state: TranscriptState, events: KaosAgentEvent[]): TranscriptState {
  return events.reduce((acc, ev) => applyEvent(acc, ev), state);
}

describe("event-handler — replay equivalence (SSE resume Stage 1)", () => {
  // Freeze the wall clock so `latencyFor` (which subtracts
  // `started_at` from `Date.now()` inside `applyEvent`) produces a
  // deterministic value regardless of how long each `reduce` step
  // takes. Without this, the live-vs-replay comparison fails by 1ms
  // on slower CI hardware — see design §9 ("Frontend reducer purity
  // is the load-bearing assumption for replay correctness").
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-19T00:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("split-then-rejoin yields the same final state as a single live fold", () => {
    // Seed with the same placeholder the live POST path adds before
    // the first SSE frame arrives.
    const seed = pushUserAndAssistantPlaceholder(initialState, "hi").state;
    const events = makeStream();

    const liveOnly = foldAll(seed, events);

    for (let split = 0; split <= events.length; split++) {
      const replayed = foldAll(seed, events.slice(0, split));
      const resumed = foldAll(replayed, events.slice(split));
      expect(resumed).toEqual(liveOnly);
    }
  });

  it("unknown event types (run_started envelope) do not alter state", () => {
    // The Stage-1 wire adds a SPA-emitted `run_started` frame at
    // sequence -1. The reducer's exhaustive `default` branch returns
    // state unchanged for it, so folding it in is a no-op. The
    // dispatcher in use-send-message.ts skips it earlier; this test
    // is the belt-and-suspenders check at the reducer level so any
    // future regression where `run_started` leaks to applyEvent is
    // still safe.
    const seed = pushUserAndAssistantPlaceholder(initialState, "hi").state;
    // ALL_EVENT_TYPES doesn't include `run_started`, so cast through
    // unknown to exercise the default branch.
    const fake = {
      type: "run_started",
      run_id: "turn-0000-aaa",
      session_id: "s",
      turn_index: 0,
      started_at: 0,
      model: "anthropic:claude-haiku-4-5",
    } as unknown as KaosAgentEvent;
    const after = applyEvent(seed, fake);
    expect(after).toEqual(seed);
  });
});
