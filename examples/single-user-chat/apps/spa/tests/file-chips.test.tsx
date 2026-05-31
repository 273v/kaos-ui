/**
 * <FileChips> overflow + onShowAll behavior — pins POL-F.
 *
 * Failed-parse files pin to the front of the visible window; an
 * extra "+N more" pill renders when files.length > maxVisible and
 * fires onShowAll on click.
 */

import { FileChips } from "@273v/kaos-ui-react/chat";
import type { FileMeta } from "@273v/kaos-ui-react/lib";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

function makeFile(name: string, opts: Partial<FileMeta> = {}): FileMeta {
  return {
    filename: name,
    size_bytes: 1024,
    content_type: "application/pdf",
    uploaded_at: "2026-05-14T18:00:00Z",
    parse: { status: "ready", error: null },
    ...opts,
  };
}

describe("<FileChips>", () => {
  it("renders nothing when files is empty", () => {
    const { container } = render(<FileChips files={[]} onRemove={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders one chip per file when count ≤ maxVisible", () => {
    render(
      <FileChips
        files={[makeFile("a.pdf"), makeFile("b.pdf")]}
        onRemove={() => {}}
        maxVisible={3}
      />,
    );
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/\+\d+ more/)).not.toBeInTheDocument();
  });

  it("caps visible chips at maxVisible and shows a +N more pill", () => {
    render(
      <FileChips
        files={[
          makeFile("a.pdf"),
          makeFile("b.pdf"),
          makeFile("c.pdf"),
          makeFile("d.pdf"),
          makeFile("e.pdf"),
        ]}
        onRemove={() => {}}
        maxVisible={3}
      />,
    );
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
    expect(screen.getByText("c.pdf")).toBeInTheDocument();
    expect(screen.queryByText("d.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("fires onShowAll when the overflow pill is clicked", () => {
    const onShowAll = vi.fn();
    render(
      <FileChips
        files={[makeFile("a.pdf"), makeFile("b.pdf"), makeFile("c.pdf"), makeFile("d.pdf")]}
        onRemove={() => {}}
        maxVisible={3}
        onShowAll={onShowAll}
      />,
    );
    fireEvent.click(screen.getByText("+1 more"));
    expect(onShowAll).toHaveBeenCalledOnce();
  });

  it("pins failed files to the front of the visible window", () => {
    const failed = makeFile("zz-bad.pdf", {
      parse: { status: "failed", error: "garbled" },
    });
    render(
      <FileChips
        files={[
          makeFile("a.pdf"),
          makeFile("b.pdf"),
          makeFile("c.pdf"),
          failed, // would be off-screen at maxVisible=3 if order weren't adjusted
        ]}
        onRemove={() => {}}
        maxVisible={3}
      />,
    );
    expect(screen.getByText("zz-bad.pdf")).toBeInTheDocument();
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
    expect(screen.queryByText("c.pdf")).not.toBeInTheDocument();
  });

  it("disables the overflow pill when onShowAll is undefined", () => {
    render(
      <FileChips
        files={[makeFile("a.pdf"), makeFile("b.pdf"), makeFile("c.pdf"), makeFile("d.pdf")]}
        onRemove={() => {}}
        maxVisible={3}
      />,
    );
    const pill = screen.getByText("+1 more").closest("button");
    expect(pill).toBeDisabled();
  });

  it("calls onRemove with the filename when X is clicked", () => {
    const onRemove = vi.fn();
    render(<FileChips files={[makeFile("a.pdf")]} onRemove={onRemove} maxVisible={3} />);
    fireEvent.click(screen.getByLabelText("Remove a.pdf"));
    expect(onRemove).toHaveBeenCalledWith("a.pdf");
  });
});
