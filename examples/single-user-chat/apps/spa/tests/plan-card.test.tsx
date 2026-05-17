/**
 * <PlanCard> — VIS-3 inline plan rendering. Pins the per-step status
 * mapping (waiting / running / done / error) so the user always sees
 * what the agent decided to do and how far it's gotten.
 */

import { PlanCard } from "@273v/kaos-ui-react/chat";
import type { PlanSnapshot } from "@273v/kaos-ui-react/lib";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function makePlan(overrides: Partial<PlanSnapshot> = {}): PlanSnapshot {
  return {
    strategy: "decompose",
    steps: [
      {
        step_id: "s1",
        description: "Search Federal Register for cybersecurity",
        tool_name: "kaos-source-fr-search",
        status: "done",
        result_preview: "Found 38 documents",
      },
      {
        step_id: "s2",
        description: "Fetch full text of FR Doc 2024-11116",
        tool_name: "kaos-source-fr-get-content",
        status: "running",
      },
      {
        step_id: "s3",
        description: "Extract defined terms",
        status: "waiting",
      },
    ],
    ...overrides,
  };
}

describe("<PlanCard>", () => {
  it("renders a collapsed summary that names the running step", () => {
    render(<PlanCard plan={makePlan()} />);
    // Strategy label visible in the header.
    expect(screen.getByText("decompose")).toBeInTheDocument();
    // Summary mentions the running step's description.
    expect(
      screen.getByText(/step 2 of 3.*Fetch full text of FR Doc 2024-11116/),
    ).toBeInTheDocument();
    // Step list hidden until expanded.
    expect(screen.queryByText("Search Federal Register for cybersecurity")).not.toBeInTheDocument();
  });

  it("expands to show the full step list with status labels", () => {
    render(<PlanCard plan={makePlan()} />);
    fireEvent.click(screen.getByRole("button", { name: /Plan/ }));
    expect(screen.getByText("Search Federal Register for cybersecurity")).toBeInTheDocument();
    expect(screen.getByText("Fetch full text of FR Doc 2024-11116")).toBeInTheDocument();
    expect(screen.getByText("Extract defined terms")).toBeInTheDocument();
    // Status labels — one per step.
    expect(screen.getByText("done")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("queued")).toBeInTheDocument();
  });

  it("starts expanded when defaultOpen is true (in-flight turn)", () => {
    render(<PlanCard plan={makePlan()} defaultOpen />);
    expect(screen.getByText("Search Federal Register for cybersecurity")).toBeInTheDocument();
  });

  it("renders tool_name as monospaced metadata under each step", () => {
    render(<PlanCard plan={makePlan()} defaultOpen />);
    expect(screen.getByText("kaos-source-fr-search")).toBeInTheDocument();
    expect(screen.getByText("kaos-source-fr-get-content")).toBeInTheDocument();
  });

  it("shows the result preview under a completed step", () => {
    render(<PlanCard plan={makePlan()} defaultOpen />);
    expect(screen.getByText(/→ Found 38 documents/)).toBeInTheDocument();
  });

  it("reports the failure count in the summary when any step errored", () => {
    const plan = makePlan({
      steps: [
        { step_id: "s1", description: "Fetch URL", status: "error" },
        { step_id: "s2", description: "Other", status: "done" },
      ],
    });
    render(<PlanCard plan={plan} />);
    expect(screen.getByText(/1 of 2 step.* failed/)).toBeInTheDocument();
  });

  it("reports completion in the summary when all steps are done", () => {
    const plan = makePlan({
      steps: [
        { step_id: "s1", description: "Step one", status: "done" },
        { step_id: "s2", description: "Step two", status: "done" },
      ],
    });
    render(<PlanCard plan={plan} />);
    expect(screen.getByText(/2 steps done/)).toBeInTheDocument();
  });

  it("singular pluralization for a one-step plan", () => {
    const plan = makePlan({
      strategy: "direct",
      steps: [{ step_id: "s1", description: "Only", status: "done" }],
    });
    render(<PlanCard plan={plan} />);
    // "1 step done" not "1 steps done"
    expect(screen.getByText(/1 step done/)).toBeInTheDocument();
    // Direct strategy isn't shown in the header (it's the default)
    expect(screen.queryByText("direct")).not.toBeInTheDocument();
  });

  it("renders each step in order using a stable numbering", () => {
    render(<PlanCard plan={makePlan()} defaultOpen />);
    const list = screen.getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]?.textContent).toMatch(/^1\.\s*Search Federal Register/);
    expect(items[1]?.textContent).toMatch(/^2\.\s*Fetch full text/);
    expect(items[2]?.textContent).toMatch(/^3\.\s*Extract defined terms/);
  });
});
