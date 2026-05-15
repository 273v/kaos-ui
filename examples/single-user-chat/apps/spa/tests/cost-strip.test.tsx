/**
 * <CostStrip> planner-cost row — pins TR-10.
 *
 * The Planner row appears only when `tool_policy_decided` events with
 * non-zero cost have been observed. We mix planner + usage_observed
 * events in a single stream to mirror the live SSE shape.
 */

import { CostStrip } from "@273v/kaos-ui-react/debug";
import type { KaosAgentEvent } from "@273v/kaos-ui-react/lib";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function usage(event: Partial<KaosAgentEvent>): KaosAgentEvent {
  return {
    type: "usage_observed",
    total_tokens: 100,
    input_tokens: 80,
    output_tokens: 20,
    cost_usd: 0.0025,
    source: "react",
    ...event,
  } as KaosAgentEvent;
}

function policy(cost: number, turn: string[] = ["web"]): KaosAgentEvent {
  return {
    type: "tool_policy_decided",
    turn_groups: turn,
    ceiling_groups: ["documents", "citations", "vfs", "web"],
    reasoning: "x",
    confidence: 0.9,
    fell_back_to_ceiling: false,
    cost_usd: cost,
    latency_ms: 1100,
  } as KaosAgentEvent;
}

describe("<CostStrip> planner row (TR-10)", () => {
  it("renders the Planner row when any tool_policy_decided has cost", () => {
    render(
      <CostStrip
        events={[usage({ cost_usd: 0.01 }), policy(0.0012), usage({ cost_usd: 0.005 })]}
      />,
    );
    expect(screen.getByText("Planner")).toBeInTheDocument();
    // Single planner call, sub-cent formatting.
    expect(screen.getByText(/1 turn/)).toBeInTheDocument();
    // The planner cost is shown alongside.
    expect(screen.getByText(/\$0\.0012/)).toBeInTheDocument();
  });

  it("aggregates across multiple planner events", () => {
    render(
      <CostStrip
        events={[usage({}), policy(0.001), policy(0.002), policy(0.0015)]}
      />,
    );
    expect(screen.getByText(/3 turns/)).toBeInTheDocument();
    // 0.001 + 0.002 + 0.0015 = 0.0045
    expect(screen.getByText(/\$0\.0045/)).toBeInTheDocument();
  });

  it("hides the row when no planner events have positive cost", () => {
    render(<CostStrip events={[usage({}), policy(0)]} />);
    expect(screen.queryByText("Planner")).not.toBeInTheDocument();
  });

  it("hides the row when no tool_policy_decided events are present", () => {
    render(<CostStrip events={[usage({})]} />);
    expect(screen.queryByText("Planner")).not.toBeInTheDocument();
  });
});
