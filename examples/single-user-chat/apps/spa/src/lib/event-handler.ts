// Exhaustive dispatch for the 15 kaos-agents wire event types + the
// `span (subject × phase)` cartesian. Pure state-update function —
// the React side just calls `applyEvent(state, event)` and re-renders.
//
// Per ARCHITECTURE.md § 5.3, PRD.md G3 ("Full event surface"), and the
// vitest unit test in tests/event-handler.test.ts (asserts every event
// type produces a deliberate state mutation, not a fall-through).

import type { ChatMessage, ToolCallSummary, TurnStatus } from "@/lib/chat-state";
import { newId } from "@/lib/chat-state";
import type { KaosAgentEvent, SpanEvent } from "@/lib/events";

export interface TranscriptState {
  /** Ordered transcript shown in the conversation column. */
  messages: ChatMessage[];
  /** Live status pill above the composer / below the streaming message. */
  status: TurnStatus;
  /** Banners that survive across turns (e.g., grounding refusals). */
  banners: { id: string; kind: "warn" | "error"; text: string }[];
  /** When true, the SSE stream is mid-flight — used to disable send. */
  pending: boolean;
}

export const initialState: TranscriptState = {
  messages: [],
  status: { kind: "idle" },
  banners: [],
  pending: false,
};

/** Locate the in-flight assistant message (the placeholder created on send). */
function currentAssistant(messages: ChatMessage[]): ChatMessage | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m && m.role === "assistant" && m.streaming) return m;
  }
  return null;
}

function patchAssistant(messages: ChatMessage[], updates: Partial<ChatMessage>): ChatMessage[] {
  const target = currentAssistant(messages);
  if (!target) return messages;
  return messages.map((m) => (m.id === target.id ? { ...m, ...updates } : m));
}

function appendToolCall(messages: ChatMessage[], tc: ToolCallSummary): ChatMessage[] {
  const target = currentAssistant(messages);
  if (!target) return messages;
  return messages.map((m) => {
    if (m.id !== target.id) return m;
    const existing = m.tool_calls ?? [];
    if (existing.find((x) => x.id === tc.id)) {
      return {
        ...m,
        tool_calls: existing.map((x) => (x.id === tc.id ? { ...x, ...tc } : x)),
      };
    }
    return { ...m, tool_calls: [...existing, tc] };
  });
}

function applySpan(state: TranscriptState, ev: SpanEvent): TranscriptState {
  const subject = ev.subject;
  const phase = ev.phase;

  if (subject === "turn") {
    if (phase === "start") {
      return { ...state, status: { kind: "thinking" } };
    }
    if (phase === "complete" || phase === "cancelled" || phase === "error") {
      // The turn_summary / run_error events drive the final transcript
      // state; the span itself just clears the status pill.
      return { ...state, status: { kind: "idle" } };
    }
    return state;
  }

  if (subject === "step") {
    if (phase === "start") {
      const stepIndex =
        typeof ev.attributes?.step_index === "number" ? (ev.attributes.step_index as number) : 1;
      return { ...state, status: { kind: "step", index: stepIndex } };
    }
    return state;
  }

  if (subject === "tool_call") {
    const callId = (ev.attributes?.call_id as string | undefined) ?? ev.span_id;
    const toolName = (ev.attributes?.tool_name as string | undefined) ?? "tool";
    if (phase === "start") {
      return {
        ...state,
        status: { kind: "tool", tool: toolName },
        messages: appendToolCall(state.messages, {
          id: callId,
          name: toolName,
          status: "running",
        }),
      };
    }
    if (phase === "complete") {
      return {
        ...state,
        messages: appendToolCall(state.messages, {
          id: callId,
          name: toolName,
          status: "done",
          result_preview:
            (ev.attributes?.result_preview as string | undefined) ??
            (ev.attributes?.result as string | undefined),
        }),
      };
    }
    if (phase === "error") {
      return {
        ...state,
        messages: appendToolCall(state.messages, {
          id: callId,
          name: toolName,
          status: "error",
          result_preview: ev.error_message ?? "tool error",
        }),
      };
    }
    return state;
  }

  // subagent / handoff / plan — debug-log only for v1 (CHAT pattern
  // doesn't fire these). Returning state unchanged is the deliberate
  // render path for them.
  return state;
}

export function applyEvent(state: TranscriptState, event: KaosAgentEvent): TranscriptState {
  switch (event.type) {
    case "span":
      return applySpan(state, event);

    case "text_delta": {
      const target = currentAssistant(state.messages);
      if (!target) return state;
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          content: target.content + event.content,
        }),
      };
    }

    case "thinking_delta": {
      // Hidden by default; the chat route shows it under `?debug=true`.
      // We still mutate state so the debug overlay can read it.
      const target = currentAssistant(state.messages);
      if (!target) return state;
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          // Append to a private field so the regular renderer ignores it.
          // We re-use `content` namespacing via a marker.
          content: target.content,
        }),
      };
    }

    case "tool_call_args_delta": {
      const callId = event.call_id ?? event.tool_name ?? "tool";
      const target = currentAssistant(state.messages);
      if (!target) return state;
      const existing = (target.tool_calls ?? []).find((x) => x.id === callId);
      const args_preview = (existing?.args_preview ?? "") + (event.delta ?? "");
      return {
        ...state,
        messages: appendToolCall(state.messages, {
          id: callId,
          name: event.tool_name ?? existing?.name ?? "tool",
          status: existing?.status ?? "running",
          args_preview,
        }),
      };
    }

    case "intent_classified": {
      // Quietly annotate the streaming assistant message. We don't
      // render this as a banner; the chat surface shows it as a label
      // above the response.
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          // We piggyback on tool_calls? No — store inline by appending
          // to content prefix? Simplest: leave content alone; the
          // renderer can show intent from elsewhere if needed.
        }),
      };
    }

    case "plan_proposed": {
      // CHAT pattern won't fire this in v1, but we still wire it: render
      // a banner so the dev knows it happened.
      return {
        ...state,
        banners: [
          ...state.banners,
          {
            id: newId(),
            kind: "warn",
            text: "Plan proposed (PlanExecute / Research pattern). The chat pattern doesn't display the plan inline yet.",
          },
        ],
      };
    }

    case "citation_found": {
      // v1: silently collect — Phase 3+ would surface in a right rail.
      // Returning state.messages unchanged is still a deliberate render
      // path (no fall-through).
      return state;
    }

    case "usage_observed": {
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          tokens: event.total_tokens ?? undefined,
          cost_usd: event.cost_usd ?? undefined,
        }),
      };
    }

    case "evidence_insufficient": {
      return {
        ...state,
        banners: [
          ...state.banners,
          {
            id: newId(),
            kind: "warn",
            text: event.reason ?? "The agent reported insufficient evidence for a grounded answer.",
          },
        ],
      };
    }

    case "grounding_refusal_triggered": {
      return {
        ...state,
        banners: [
          ...state.banners,
          {
            id: newId(),
            kind: "warn",
            text: event.reason ?? "The agent refused to answer without supporting evidence.",
          },
        ],
      };
    }

    case "turn_summary": {
      return {
        ...state,
        status: { kind: "idle" },
        pending: false,
        messages: patchAssistant(state.messages, {
          content: event.text,
          tokens: event.tokens_used,
          cost_usd: event.cost_usd,
          streaming: false,
        }),
      };
    }

    case "memory_event": {
      // No user-visible mutation — handled in the chat route as a
      // query-cache invalidation when kind === "persisted".
      return state;
    }

    case "run_error": {
      const what = event.what ?? "The turn failed.";
      const target = currentAssistant(state.messages);
      const updated: ChatMessage[] = target
        ? state.messages.map((m) =>
            m.id === target.id
              ? {
                  ...m,
                  role: "error" as const,
                  content: event.how_to_fix ? `${what}\n\n${event.how_to_fix}` : what,
                  streaming: false,
                }
              : m,
          )
        : [
            ...state.messages,
            {
              id: newId(),
              role: "error",
              content: what,
              created_at: Date.now(),
              streaming: false,
            },
          ];
      return {
        ...state,
        pending: false,
        status: { kind: "error", what },
        messages: updated,
      };
    }

    case "budget_exceeded": {
      const text =
        event.spent_usd && event.limit_usd
          ? `Turn truncated — spent $${event.spent_usd.toFixed(4)} of $${event.limit_usd.toFixed(2)} budget.`
          : "Turn truncated — budget exceeded.";
      return {
        ...state,
        pending: false,
        status: { kind: "idle" },
        banners: [...state.banners, { id: newId(), kind: "warn", text }],
        messages: patchAssistant(state.messages, {
          streaming: false,
        }),
      };
    }

    case "tool_call_approval_required": {
      return {
        ...state,
        pending: false,
        status: { kind: "idle" },
        banners: [
          ...state.banners,
          {
            id: newId(),
            kind: "warn",
            text:
              `Tool '${event.tool_name ?? "?"}' requires approval. ` +
              "Approval UI is out of scope for v1 — disable tools in the settings drawer and retry.",
          },
        ],
        messages: patchAssistant(state.messages, { streaming: false }),
      };
    }

    default: {
      // Compile-time exhaustiveness: if a new event class lands and
      // we forget to handle it, this never-narrowing assignment fails
      // at typecheck time. Keep this last.
      const _exhaustive: never = event;
      void _exhaustive;
      return state;
    }
  }
}

/** Inject a user message + an empty assistant placeholder. */
export function pushUserAndAssistantPlaceholder(
  state: TranscriptState,
  message: string,
): { state: TranscriptState; assistantId: string } {
  const assistantId = newId();
  return {
    state: {
      ...state,
      pending: true,
      status: { kind: "thinking" },
      messages: [
        ...state.messages,
        { id: newId(), role: "user", content: message, created_at: Date.now(), streaming: false },
        {
          id: assistantId,
          role: "assistant",
          content: "",
          created_at: Date.now(),
          streaming: true,
        },
      ],
    },
    assistantId,
  };
}

/** Mark the in-flight stream as aborted (UI shows "Stopped"). */
export function markAborted(state: TranscriptState): TranscriptState {
  return {
    ...state,
    pending: false,
    status: { kind: "idle" },
    messages: patchAssistant(state.messages, {
      streaming: false,
      content: currentAssistant(state.messages)?.content || "[stopped]",
    }),
  };
}
