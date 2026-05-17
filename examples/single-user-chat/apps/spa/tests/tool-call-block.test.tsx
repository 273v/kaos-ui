/**
 * <ToolCallBlock> VIS-4 redesign — friendly label, structured result
 * view, raw-toggle + copy-as-JSON, collapsed inline summary.
 */

import { ToolCallBlock } from "@273v/kaos-ui-react/chat";
import type { ToolCallSummary } from "@273v/kaos-ui-react/lib";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function makeCall(overrides: Partial<ToolCallSummary> = {}): ToolCallSummary {
  return {
    id: "c1",
    name: "kaos-source-fr-search",
    status: "done",
    args_preview: '{"q":"cheese"}',
    result_preview:
      'Found 9 Federal Register document(s), showing 9\n\n{"results": [{"document_number":"2026-12345","title":"Cheese standards","type":"Rule","publication_date":"2026-05-01","html_url":"https://example/x"}]}',
    ...overrides,
  };
}

describe("<ToolCallBlock>", () => {
  it("renders a friendly label and the result lead-in in the collapsed header", () => {
    render(<ToolCallBlock call={makeCall()} />);
    // Friendly label, not the raw tool id.
    expect(screen.getByText("Federal Register · Search")).toBeInTheDocument();
    // Result summary uses the lead-in line, not the JSON blob.
    expect(screen.getByText(/Found 9 documents/)).toBeInTheDocument();
    // The chip should NOT show the raw {"results":...} blob.
    expect(screen.queryByText(/\{"results"/)).not.toBeInTheDocument();
    // Body labels hidden until expanded.
    expect(screen.queryByText("arguments")).not.toBeInTheDocument();
    expect(screen.queryByText("result")).not.toBeInTheDocument();
  });

  it("shows compact args summary derived from JSON args_preview", () => {
    render(<ToolCallBlock call={makeCall()} />);
    // {"q":"cheese"} → `q="cheese"`
    expect(screen.getByText('q="cheese"')).toBeInTheDocument();
  });

  it("starts collapsed by default", () => {
    render(<ToolCallBlock call={makeCall()} />);
    expect(screen.getByRole("button", { expanded: false })).toBeInTheDocument();
  });

  it("starts open when defaultOpen is true", () => {
    render(<ToolCallBlock call={makeCall()} defaultOpen />);
    expect(screen.getByRole("button", { name: /Federal Register · Search/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("arguments")).toBeInTheDocument();
    expect(screen.getByText("result")).toBeInTheDocument();
  });

  it("renders fr-search result as a structured card with title + doc# + link", () => {
    render(<ToolCallBlock call={makeCall()} defaultOpen />);
    expect(screen.getByText("Cheese standards")).toBeInTheDocument();
    expect(screen.getByText("2026-12345")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /open/i });
    expect(link).toHaveAttribute("href", "https://example/x");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("offers a 'show raw' toggle that swaps the structured view for the wire JSON", () => {
    render(<ToolCallBlock call={makeCall()} defaultOpen />);
    expect(screen.getByText("Cheese standards")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show raw/i }));
    // After toggling, the cleaned label disappears and the raw blob is visible.
    expect(screen.queryByText("Cheese standards")).not.toBeInTheDocument();
    expect(screen.getByText(/\{"results"/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /structured view/i })).toBeInTheDocument();
  });

  it("offers a copy-json affordance", () => {
    render(<ToolCallBlock call={makeCall()} defaultOpen />);
    // aria-label is "Copy raw call JSON"; visible text is "copy json".
    expect(screen.getByRole("button", { name: /copy raw call json/i })).toBeInTheDocument();
  });

  it("expands when the header is clicked", () => {
    render(<ToolCallBlock call={makeCall()} />);
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("arguments")).toBeInTheDocument();
    expect(screen.getByText("result")).toBeInTheDocument();
  });

  it("re-syncs when defaultOpen flips after first render", () => {
    const { rerender } = render(<ToolCallBlock call={makeCall()} defaultOpen={false} />);
    expect(screen.queryByText("arguments")).not.toBeInTheDocument();
    rerender(<ToolCallBlock call={makeCall()} defaultOpen />);
    expect(screen.getByText("arguments")).toBeInTheDocument();
  });

  it("shows 'running…' instead of a preview when no result_preview yet", () => {
    render(
      <ToolCallBlock call={makeCall({ status: "running", result_preview: undefined })} />,
    );
    expect(screen.getByText(/running/)).toBeInTheDocument();
  });

  it("renders an error fallback when status is error and no result_preview", () => {
    render(
      <ToolCallBlock call={makeCall({ status: "error", result_preview: undefined })} defaultOpen />,
    );
    expect(screen.getByText(/tool call failed/i)).toBeInTheDocument();
  });

  it("falls back to a humanized label for unknown tool ids", () => {
    render(
      <ToolCallBlock
        call={makeCall({ name: "kaos-future-tool-x", result_preview: undefined })}
      />,
    );
    expect(screen.getByText("Future Tool X")).toBeInTheDocument();
  });

  it("renders fr-get-content result as a doc card with title + citation", () => {
    const call = makeCall({
      name: "kaos-source-fr-get-content",
      args_preview: undefined,
      result_preview:
        'Regulation S-P: Privacy of Consumer Financial Information — 50000 chars (text) (truncated)\n\n{"document_number":"2024-11116","title":"Regulation S-P","citation":"89 FR 47688","action":"Rule","html_url":"https://example/sp"}',
    });
    render(<ToolCallBlock call={call} defaultOpen />);
    // Header surfaces the doc title condensed.
    expect(screen.getByText(/Regulation S-P: Privacy of Consumer Financial Information/)).toBeInTheDocument();
    // Expanded body: doc card with citation.
    expect(screen.getByText(/89 FR 47688/)).toBeInTheDocument();
    // Args summary in header shows derived "doc 2024-11116" since args_preview is empty.
    expect(screen.getByText(/doc 2024-11116/)).toBeInTheDocument();
  });

  it("renders fetch-url result as a clickable link card", () => {
    const call = makeCall({
      name: "kaos-source-fetch-url",
      args_preview: undefined,
      result_preview:
        'Fetched regulation-s-p.html (10.3 KB)\n\n{"artifact_id":"abc","url":"https://www.federalregister.gov/x"}',
    });
    render(<ToolCallBlock call={call} defaultOpen />);
    const links = screen.getAllByRole("link");
    expect(links.some((a) => a.getAttribute("href") === "https://www.federalregister.gov/x")).toBe(
      true,
    );
  });
});
