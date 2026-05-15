/**
 * <ToolPolicyBadge> rendering + interaction — pins TR-9 / TR-12.
 *
 * Two main paths:
 *   - Narrowed: green-ish badge with "Tools: web · 95%".
 *   - Fell-back: warn-tinted badge with "Tools: documents, citations, vfs".
 * Clicking either toggles a popover with the reasoning + cost line.
 */

import { ToolPolicyBadge } from "@273v/kaos-ui-react/chat";
import type { ToolPolicySnapshot } from "@273v/kaos-ui-react/lib";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function makePolicy(overrides: Partial<ToolPolicySnapshot> = {}): ToolPolicySnapshot {
  return {
    turn_groups: ["web"],
    ceiling_groups: ["documents", "citations", "vfs", "web"],
    reasoning: "User asked to search Federal Register.",
    confidence: 0.95,
    fell_back_to_ceiling: false,
    cost_usd: 0.001,
    latency_ms: 1100,
    ...overrides,
  };
}

describe("<ToolPolicyBadge>", () => {
  it("returns null when no policy is attached", () => {
    const { container } = render(<ToolPolicyBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows narrowed group list + confidence in the closed badge", () => {
    render(<ToolPolicyBadge policy={makePolicy()} />);
    expect(screen.getByText(/Tools:/)).toBeInTheDocument();
    expect(screen.getByText(/web/)).toBeInTheDocument();
    expect(screen.getByText(/95%/)).toBeInTheDocument();
  });

  it("expands a popover with reasoning + cost on click", () => {
    render(<ToolPolicyBadge policy={makePolicy()} />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("User asked to search Federal Register.")).toBeInTheDocument();
    // Cost is shown alongside latency.
    expect(screen.getByText(/\$0\.0010/)).toBeInTheDocument();
    expect(screen.getByText(/1\.1s/)).toBeInTheDocument();
  });

  it("renders a different visual variant when planner fell back", () => {
    const policy = makePolicy({
      turn_groups: ["documents", "citations", "vfs"],
      fell_back_to_ceiling: true,
      confidence: 0.4,
      reasoning: "Ambiguous question; using full ceiling.",
    });
    render(<ToolPolicyBadge policy={policy} />);
    const btn = screen.getByRole("button");
    // Fallback badge omits the confidence chip in the closed view.
    expect(btn).not.toHaveTextContent("40%");
    // Title hint flags the abdication.
    expect(btn.getAttribute("title")).toMatch(/abdicat/i);
  });

  it("formats sub-cent cost as <$0.0001", () => {
    const policy = makePolicy({ cost_usd: 0.00005 });
    render(<ToolPolicyBadge policy={policy} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/<\$0\.0001/)).toBeInTheDocument();
  });

  it("handles empty turn_groups (full lockdown) gracefully", () => {
    const policy = makePolicy({
      turn_groups: [],
      ceiling_groups: [],
      reasoning: "Tools disabled for this session.",
      fell_back_to_ceiling: false,
    });
    render(<ToolPolicyBadge policy={policy} />);
    expect(screen.getByText(/no tools/i)).toBeInTheDocument();
  });
});
