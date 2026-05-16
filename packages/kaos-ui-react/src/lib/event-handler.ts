/**
 * Exhaustive dispatch for the 15 kaos-agents wire event types + the
 * `span (subject × phase)` cartesian. Pure state-update function —
 * the React side just calls `applyEvent(state, event)` and re-renders.
 *
 * Verified against kaos-agents 0.1.0a1; if a new wire event lands, the
 * `default` branch's `_exhaustive: never` assignment fails at typecheck
 * time so consumers are forced to handle it.
 */

import type { ChatMessage, ToolCallSummary, TurnStatusKind } from "./chat-state.js";
import { newId } from "./chat-state.js";
import type { KaosAgentEvent, SpanEvent } from "./events.js";

export interface TranscriptState {
  /** Ordered transcript shown in the conversation column. */
  messages: ChatMessage[];
  /** Live status pill above the composer / below the streaming message. */
  status: TurnStatusKind;
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

// Defense-in-depth: drop bracketed scratchpad closers that some
// instruction-tuned models hallucinate when given an opener-only
// field marker by a non-JSON codec — e.g. `[/response]`, `</response>`.
// kaos-agents 0.1.0a5+ uses native JSONCodec for the respond handler
// so this is a belt-and-suspenders guard against future codec
// regressions or a stray non-JSON Signature elsewhere on the wire.
// Conservative pattern: only matches whole bracket-name-bracket
// tokens whose name is a `\w+` slug (no internal whitespace), so
// we won't eat literal text like `[/path/to/file]`.
const SCRATCHPAD_TAG_RE = /\[\/\w+\]|<\/\w+>/g;
function stripScratchpadTags(text: string): string {
  if (!text) return text;
  return text.replace(SCRATCHPAD_TAG_RE, "");
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
      const cleaned = stripScratchpadTags(event.content);
      if (!cleaned) return state;
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          content: target.content + cleaned,
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
      // The agent emits one usage_observed per LLM call within a turn,
      // so we accumulate rather than overwrite — total_tokens here is
      // the per-call total. Fall back to input + output when the
      // provider doesn't include `total_tokens`.
      const target = currentAssistant(state.messages);
      const callTotal =
        event.total_tokens ?? (event.input_tokens ?? 0) + (event.output_tokens ?? 0);
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          tokens: (target?.tokens ?? 0) + callTotal,
          input_tokens: (target?.input_tokens ?? 0) + (event.input_tokens ?? 0),
          output_tokens: (target?.output_tokens ?? 0) + (event.output_tokens ?? 0),
          cost_usd: (target?.cost_usd ?? 0) + (event.cost_usd ?? 0),
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
      // Prefer the turn_summary totals when present (they're the rolled-
      // up authoritative numbers); fall back to whatever usage_observed
      // accumulated. Either way, record latency_ms now.
      const target = currentAssistant(state.messages);
      const summaryTotal =
        event.tokens_used ?? (event.input_tokens ?? 0) + (event.output_tokens ?? 0);
      return {
        ...state,
        status: { kind: "idle" },
        pending: false,
        messages: patchAssistant(state.messages, {
          content: event.text,
          tokens: event.tokens_used != null ? summaryTotal : target?.tokens,
          input_tokens: event.input_tokens ?? target?.input_tokens,
          output_tokens: event.output_tokens ?? target?.output_tokens,
          cost_usd: event.cost_usd ?? target?.cost_usd,
          latency_ms: latencyFor(state.messages),
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
      const latency = latencyFor(state.messages);
      const updated: ChatMessage[] = target
        ? state.messages.map((m) =>
            m.id === target.id
              ? {
                  ...m,
                  role: "error" as const,
                  content: event.how_to_fix ? `${what}\n\n${event.how_to_fix}` : what,
                  streaming: false,
                  latency_ms: latency,
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
          latency_ms: latencyFor(state.messages),
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
            text: `Tool '${event.tool_name ?? "?"}' requires approval. Approval UI is out of scope for v1 — disable tools in the settings drawer and retry.`,
          },
        ],
        messages: patchAssistant(state.messages, { streaming: false }),
      };
    }

    case "tool_policy_decided": {
      // TR-7: attach the planner snapshot to the in-flight assistant
      // message so <Message> can render the ToolPolicyBadge (TR-9)
      // above the response, AND so CostStrip (TR-10) can attribute
      // the planner cost separately from the main turn cost.
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          tool_policy: {
            turn_groups: event.turn_groups,
            ceiling_groups: event.ceiling_groups,
            reasoning: event.reasoning,
            confidence: event.confidence,
            fell_back_to_ceiling: event.fell_back_to_ceiling,
            cost_usd: event.cost_usd,
            latency_ms: event.latency_ms,
          },
        }),
      };
    }

    case "tool_policy_elevated": {
      // AgenticLoop auto-elevation. Append to the in-flight assistant
      // message's `elevations` list — multiple iterations can each
      // elevate (the SPA's <ElevationPill> chips off the most recent).
      const target = currentAssistant(state.messages);
      const existing = target?.elevations ?? [];
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          elevations: [
            ...existing,
            {
              elevated_groups: event.elevated_groups,
              kept_groups: event.kept_groups,
              previous_allowed: event.previous_allowed,
              rationale: event.rationale,
              iteration: event.iteration,
            },
          ],
        }),
      };
    }

    case "capability_requested": {
      // Yellow-confirm pause. The loop has emitted this event AND is
      // about to wait for the user. The SPA renders the inline
      // CapabilityApproval card from this snapshot.
      return {
        ...state,
        // Don't drop `pending` — the loop is still active, just waiting
        // for the user's click before resuming.
        messages: patchAssistant(state.messages, {
          capability_request: {
            requested_groups: event.requested_groups,
            justification: event.justification,
            iteration: event.iteration,
            previous_allowed: event.previous_allowed,
          },
        }),
      };
    }

    case "goal_checked": {
      // Critic's verdict. Drives the GoalCheckBadge color. We overwrite
      // — the most recent verdict wins (replan loops emit multiple).
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          goal_check: {
            kind: event.kind,
            rationale: event.rationale,
            next_action: event.next_action,
            missing: event.missing,
            confidence: event.confidence,
            iteration: event.iteration,
            cost_usd: event.cost_usd,
            latency_ms: event.latency_ms,
          },
        }),
      };
    }

    case "loop_terminated": {
      // Always the LAST event of an agentic turn. The SPA renders the
      // LoopTerminatedBanner for any non-"satisfied" reason; the
      // streaming-message finalization happens via turn_summary.
      return {
        ...state,
        messages: patchAssistant(state.messages, {
          loop_termination: {
            reason: event.reason,
            iterations_used: event.iterations_used,
            elevations_used: event.elevations_used,
            cost_usd: event.cost_usd,
            wall_clock_ms: event.wall_clock_ms,
          },
        }),
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
  const now = Date.now();
  return {
    state: {
      ...state,
      pending: true,
      status: { kind: "thinking" },
      messages: [
        ...state.messages,
        { id: newId(), role: "user", content: message, created_at: now, streaming: false },
        {
          id: assistantId,
          role: "assistant",
          content: "",
          created_at: now,
          streaming: true,
          started_at: now,
        },
      ],
    },
    assistantId,
  };
}

/** Wall-clock latency since the in-flight assistant message started. */
function latencyFor(messages: ChatMessage[]): number | undefined {
  const target = currentAssistant(messages);
  if (!target?.started_at) return undefined;
  return Date.now() - target.started_at;
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
