/**
 * <ToolCallBlock> defaultOpen + inline result preview — pins POL-G.
 */

import { ToolCallBlock } from "@273v/kaos-ui-react/chat";
import type { ToolCallSummary } from "@273v/kaos-ui-react/lib";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function makeCall(overrides: Partial<ToolCallSummary> = {}): ToolCallSummary {
  return {
    id: "c1",
    name: "kaos-source-fr-search",
    status: "done",
    args_preview: '{"q":"cheese"}',
    result_preview: '[{"document_number":"2026-12345","title":"Cheese standards"}]',
    ...overrides,
  };
}

describe("<ToolCallBlock>", () => {
  it("renders the inline 1-line result preview without expanding", () => {
    render(<ToolCallBlock call={makeCall()} />);
    expect(screen.getByText("kaos-source-fr-search")).toBeInTheDocument();
    // Preview is rendered as text with a leading arrow.
    expect(screen.getByText(/→/)).toBeInTheDocument();
    expect(screen.getByText(/document_number/)).toBeInTheDocument();
    // Body labels are hidden until expanded.
    expect(screen.queryByText("arguments")).not.toBeInTheDocument();
    expect(screen.queryByText("result")).not.toBeInTheDocument();
  });

  it("starts collapsed by default", () => {
    render(<ToolCallBlock call={makeCall()} />);
    const toggle = screen.getByRole("button", { expanded: false });
    expect(toggle).toBeInTheDocument();
  });

  it("starts open when defaultOpen is true", () => {
    render(<ToolCallBlock call={makeCall()} defaultOpen />);
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(screen.getByText("arguments")).toBeInTheDocument();
    expect(screen.getByText("result")).toBeInTheDocument();
  });

  it("expands when the header is clicked", () => {
    render(<ToolCallBlock call={makeCall()} />);
    const toggle = screen.getByRole("button", { expanded: false });
    fireEvent.click(toggle);
    expect(screen.getByText("arguments")).toBeInTheDocument();
    expect(screen.getByText("result")).toBeInTheDocument();
  });

  it("re-syncs when defaultOpen flips after first render", () => {
    const { rerender } = render(
      <ToolCallBlock call={makeCall()} defaultOpen={false} />,
    );
    expect(screen.queryByText("arguments")).not.toBeInTheDocument();
    rerender(<ToolCallBlock call={makeCall()} defaultOpen />);
    expect(screen.getByText("arguments")).toBeInTheDocument();
  });

  it("shows 'running…' instead of a preview when no result_preview yet", () => {
    render(
      <ToolCallBlock
        call={makeCall({ status: "running", result_preview: undefined })}
      />,
    );
    expect(screen.getByText(/running/)).toBeInTheDocument();
  });

  it("renders an error fallback when status is error and no result_preview", () => {
    render(
      <ToolCallBlock
        call={makeCall({ status: "error", result_preview: undefined })}
        defaultOpen
      />,
    );
    expect(screen.getByText(/tool call failed/i)).toBeInTheDocument();
  });
});
