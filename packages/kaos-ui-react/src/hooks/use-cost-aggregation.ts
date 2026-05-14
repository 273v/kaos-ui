/**
 * Live cost + token aggregation across a stream of kaos-agents events.
 *
 * Consumes the raw `usage_observed` events emitted by kaos-agents
 * (one per LLM call) and rolls them up per model. Feeds the
 * <CostStrip> debug component.
 *
 * Pure derivation — re-runs whenever `events` reference changes. The
 * consumer typically holds an append-only list of events in React
 * state (see `useSendMessage.rawEvents`), so the dependency identity
 * is stable across re-renders that don't add events.
 */

import { useMemo } from "react";

import type { KaosAgentEvent } from "../lib/events.js";

export interface ModelUsage {
  /** Model id, e.g. `claude-haiku-4-5` (kaos-agents reports unprefixed). */
  model: string;
  /** Number of usage_observed events seen for this model. */
  calls: number;
  /** Sum of input tokens across all calls. */
  input_tokens: number;
  /** Sum of output tokens across all calls. */
  output_tokens: number;
  /** Sum of total_tokens (may differ from input + output for some providers). */
  total_tokens: number;
  /** Sum of cost_usd across all calls. */
  cost_usd: number;
}

export interface UseCostAggregationResult {
  /** Per-model usage rows, sorted by descending cost. */
  byModel: ModelUsage[];
  /** Aggregate across every model. */
  total: Omit<ModelUsage, "model">;
}

/**
 * Take the raw event list (typically `useSendMessage().rawEvents`)
 * and return per-model + total rollups. Wrapper-shaped values
 * (`{ _id, event }`) are supported transparently — we read `.event`
 * if present, otherwise treat the input as already-unwrapped.
 */
export function useCostAggregation(
  events: ReadonlyArray<KaosAgentEvent | { event: KaosAgentEvent }>,
): UseCostAggregationResult {
  return useMemo(() => {
    const acc = new Map<string, ModelUsage>();
    let totalCalls = 0;
    let totalInput = 0;
    let totalOutput = 0;
    let totalTokens = 0;
    let totalCost = 0;

    for (const entry of events) {
      const ev = "event" in entry ? entry.event : entry;
      if (ev.type !== "usage_observed") continue;
      const source = ev.source ?? "unknown";
      const row = acc.get(source) ?? {
        model: source,
        calls: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        cost_usd: 0,
      };
      row.calls += 1;
      row.input_tokens += ev.input_tokens ?? 0;
      row.output_tokens += ev.output_tokens ?? 0;
      row.total_tokens += ev.total_tokens ?? 0;
      row.cost_usd += ev.cost_usd ?? 0;
      acc.set(source, row);

      totalCalls += 1;
      totalInput += ev.input_tokens ?? 0;
      totalOutput += ev.output_tokens ?? 0;
      totalTokens += ev.total_tokens ?? 0;
      totalCost += ev.cost_usd ?? 0;
    }

    const byModel = Array.from(acc.values()).sort((a, b) => b.cost_usd - a.cost_usd);
    return {
      byModel,
      total: {
        calls: totalCalls,
        input_tokens: totalInput,
        output_tokens: totalOutput,
        total_tokens: totalTokens,
        cost_usd: totalCost,
      },
    };
  }, [events]);
}
