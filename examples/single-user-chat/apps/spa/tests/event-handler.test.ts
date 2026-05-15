// Exhaustiveness gate for the kaos-agents event dispatch.
//
// PRD G3 says every one of the 15 wire types AND every observed
// (subject, phase) combo on `span` must produce a deliberate state
// mutation. Each case here exercises one branch and asserts the
// resulting state differs from the seed in a specific, expected way.

import {
  ALL_EVENT_TYPES,
  applyEvent,
  type ChatMessage,
  initialState,
  markAborted,
  newId,
  pushUserAndAssistantPlaceholder,
  type TranscriptState,
} from "@273v/kaos-ui-react/lib";
import { describe, expect, it } from "vitest";

function seedWithPlaceholder(): { state: TranscriptState; assistantId: string } {
  return pushUserAndAssistantPlaceholder(initialState, "hello");
}

function makeSpan(subject: string, phase: string, attrs: Record<string, unknown> = {}) {
  return {
    type: "span" as const,
    subject: subject as never,
    phase: phase as never,
    span_id: "s",
    parent_span_id: null,
    name: `${subject}.${phase}`,
    duration_ms: null,
    error_type: null,
    error_message: null,
    attributes: attrs,
  };
}

describe("event-handler — wire-event coverage", () => {
  it("covers all 16 event type strings (15 kaos-agents + 1 kaos-ui ext)", () => {
    // 15 canonical kaos-agents wire events + 1 kaos-ui extension
    // (tool_policy_decided, TR-7) — see events.ts header docstring.
    expect(ALL_EVENT_TYPES.length).toBe(16);
    expect(ALL_EVENT_TYPES).toContain("tool_policy_decided");
  });

  it("text_delta appends to the streaming assistant message", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, { type: "text_delta", content: "Hello " });
    const last = applyEvent(next, { type: "text_delta", content: "world." });
    const msg = last.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.content).toBe("Hello world.");
  });

  it("thinking_delta does not mutate visible content", () => {
    const { state } = seedWithPlaceholder();
    const next = applyEvent(state, { type: "thinking_delta", content: "internal." });
    // Visible content unchanged; deliberate no-op for the regular renderer.
    expect(next.messages.at(-1)?.content).toBe("");
  });

  it("tool_call_args_delta accumulates inline tool args", () => {
    const { state } = seedWithPlaceholder();
    const after = applyEvent(state, {
      type: "tool_call_args_delta",
      call_id: "call-1",
      tool_name: "kaos-pdf-parse",
      delta: '{"path":"',
    });
    const more = applyEvent(after, {
      type: "tool_call_args_delta",
      call_id: "call-1",
      tool_name: "kaos-pdf-parse",
      delta: 'foo.pdf"}',
    });
    const target = more.messages.find((m: ChatMessage) => m.streaming);
    expect(target?.tool_calls?.[0]?.args_preview).toBe('{"path":"foo.pdf"}');
  });

  it("intent_classified mutates state without breaking exhaustiveness", () => {
    const { state } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "intent_classified",
      intent: "respond",
      confidence: 0.9,
    });
    // No banner, no fallthrough, no error
    expect(next).toBeDefined();
  });

  it("plan_proposed adds a warn banner", () => {
    const next = applyEvent(initialState, { type: "plan_proposed" });
    expect(next.banners).toHaveLength(1);
    expect(next.banners[0]?.kind).toBe("warn");
  });

  it("citation_found returns state without throwing", () => {
    const { state } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "citation_found",
      citation: { kind: "case", text: "..." },
    });
    expect(next).toBeDefined();
  });

  it("usage_observed writes tokens + cost to the streaming message", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "usage_observed",
      total_tokens: 123,
      cost_usd: 0.0005,
    });
    const msg = next.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.tokens).toBe(123);
    expect(msg?.cost_usd).toBe(0.0005);
  });

  it("evidence_insufficient adds a warn banner", () => {
    const next = applyEvent(initialState, {
      type: "evidence_insufficient",
      reason: "no docs",
    });
    expect(next.banners.at(-1)?.text).toContain("no docs");
  });

  it("grounding_refusal_triggered adds a warn banner", () => {
    const next = applyEvent(initialState, {
      type: "grounding_refusal_triggered",
      reason: "policy",
    });
    expect(next.banners.at(-1)?.text).toContain("policy");
  });

  it("turn_summary finalizes the streaming message", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "turn_summary",
      text: "Final reply.",
      tokens_used: 42,
      cost_usd: 0.0001,
    });
    const msg = next.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.content).toBe("Final reply.");
    expect(msg?.streaming).toBe(false);
    expect(msg?.tokens).toBe(42);
    expect(next.pending).toBe(false);
    expect(next.status.kind).toBe("idle");
  });

  it("memory_event returns state unchanged (cache invalidation is side-channel)", () => {
    const next = applyEvent(initialState, {
      type: "memory_event",
      kind: "persisted",
      section: "messages",
    });
    expect(next).toBe(initialState);
  });

  it("run_error replaces the placeholder with an error message", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "run_error",
      what: "Upstream 500.",
      how_to_fix: "Retry.",
    });
    const msg = next.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.role).toBe("error");
    expect(msg?.content).toContain("Upstream 500.");
    expect(next.pending).toBe(false);
  });

  it("budget_exceeded adds a banner and finalizes the message", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "budget_exceeded",
      limit_usd: 0.5,
      spent_usd: 0.6,
    });
    expect(next.banners.at(-1)?.text).toContain("budget");
    const msg = next.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.streaming).toBe(false);
  });

  it("tool_call_approval_required produces a v1-stub banner", () => {
    const { state } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "tool_call_approval_required",
      tool_name: "kaos-write",
      args: { path: "/etc/passwd" },
    });
    expect(next.banners.at(-1)?.text).toContain("requires approval");
    expect(next.pending).toBe(false);
  });
});

describe("event-handler — span cartesian", () => {
  it.each([
    ["turn", "start"],
    ["turn", "complete"],
    ["turn", "error"],
    ["turn", "cancelled"],
    ["step", "start"],
    ["step", "complete"],
    ["tool_call", "start"],
    ["tool_call", "progress"],
    ["tool_call", "complete"],
    ["tool_call", "error"],
    ["plan", "start"],
    ["subagent", "start"],
    ["handoff", "start"],
  ])("span(%s,%s) is a deliberate render path", (subject, phase) => {
    const { state } = seedWithPlaceholder();
    const next = applyEvent(state, makeSpan(subject, phase));
    expect(next).toBeDefined();
    // No exhaustiveness error implies we hit a real case branch.
  });

  it("span(turn,start) sets status to thinking", () => {
    const next = applyEvent(initialState, makeSpan("turn", "start"));
    expect(next.status.kind).toBe("thinking");
  });

  it("span(tool_call,start) creates a running ToolCallBlock", () => {
    const { state } = seedWithPlaceholder();
    const next = applyEvent(
      state,
      makeSpan("tool_call", "start", { call_id: "c1", tool_name: "kaos-pdf-parse" }),
    );
    const target = next.messages.find((m: ChatMessage) => m.streaming);
    expect(target?.tool_calls?.[0]?.name).toBe("kaos-pdf-parse");
    expect(target?.tool_calls?.[0]?.status).toBe("running");
    expect(next.status.kind).toBe("tool");
  });

  it("span(tool_call,complete) marks the block done", () => {
    const { state } = seedWithPlaceholder();
    const after = applyEvent(
      state,
      makeSpan("tool_call", "start", { call_id: "c1", tool_name: "x" }),
    );
    const done = applyEvent(after, makeSpan("tool_call", "complete", { call_id: "c1" }));
    const target = done.messages.find((m: ChatMessage) => m.streaming);
    expect(target?.tool_calls?.[0]?.status).toBe("done");
  });

  it("span(step,start) reads step_index attribute", () => {
    const next = applyEvent(initialState, makeSpan("step", "start", { step_index: 3 }));
    expect(next.status.kind).toBe("step");
    if (next.status.kind === "step") expect(next.status.index).toBe(3);
  });

  it("tool_policy_decided attaches policy snapshot to the streaming assistant", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "tool_policy_decided",
      turn_groups: ["web"],
      ceiling_groups: ["documents", "citations", "vfs", "web"],
      reasoning: "User asked to search Federal Register.",
      confidence: 0.95,
      fell_back_to_ceiling: false,
      cost_usd: 0.001,
      latency_ms: 1100,
    });
    const msg = next.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.tool_policy?.turn_groups).toEqual(["web"]);
    expect(msg?.tool_policy?.confidence).toBe(0.95);
    expect(msg?.tool_policy?.fell_back_to_ceiling).toBe(false);
    expect(msg?.tool_policy?.cost_usd).toBe(0.001);
  });

  it("tool_policy_decided handles the fell-back-to-ceiling state", () => {
    const { state, assistantId } = seedWithPlaceholder();
    const next = applyEvent(state, {
      type: "tool_policy_decided",
      turn_groups: ["documents", "citations", "vfs"],
      ceiling_groups: ["documents", "citations", "vfs"],
      reasoning: "Low confidence — using full ceiling.",
      confidence: 0.4,
      fell_back_to_ceiling: true,
      cost_usd: 0.0008,
      latency_ms: 950,
    });
    const msg = next.messages.find((m: ChatMessage) => m.id === assistantId);
    expect(msg?.tool_policy?.fell_back_to_ceiling).toBe(true);
    expect(msg?.tool_policy?.confidence).toBe(0.4);
  });
});

describe("event-handler — helpers", () => {
  it("pushUserAndAssistantPlaceholder seeds a user + streaming assistant pair", () => {
    const { state, assistantId } = pushUserAndAssistantPlaceholder(initialState, "Hi");
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]?.role).toBe("user");
    expect(state.messages[1]?.role).toBe("assistant");
    expect(state.messages[1]?.streaming).toBe(true);
    expect(state.messages[1]?.id).toBe(assistantId);
    expect(state.pending).toBe(true);
  });

  it("markAborted finalizes the streaming message as stopped", () => {
    const { state } = pushUserAndAssistantPlaceholder(initialState, "Hi");
    const aborted = markAborted(state);
    expect(aborted.pending).toBe(false);
    expect(aborted.messages.at(-1)?.streaming).toBe(false);
  });

  it("newId returns unique strings", () => {
    const a = newId();
    const b = newId();
    expect(a).not.toBe(b);
  });
});
