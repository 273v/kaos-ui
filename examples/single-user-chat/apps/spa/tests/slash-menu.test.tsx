/**
 * <SlashMenu> — composer slash-command popover.
 *
 * Pins the B1-family fixes from kaos-ui 0.1.0a8:
 *
 *  1. The document-level keydown listener BAILS OUT unless the
 *     composer textarea (`#composer-message`) is the active
 *     element. Means pasting `/path/to/file` + pressing Enter
 *     somewhere else does NOT trigger a skill pick.
 *
 *  2. The menu only renders when `open=true`. (Wired by the host
 *     route — typing `/` as the first char of an empty composer.)
 */

import { type Skill, SlashMenu } from "@273v/kaos-ui-react/chat";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const SKILLS: Skill[] = [
  {
    id: "search",
    name: "Search corpus",
    description: "BM25 search across attached documents.",
    prefill: "Search the corpus for ",
    persona: "research",
    allowed_groups: ["documents", "vfs"],
  },
  {
    id: "redline",
    name: "Redline",
    description: "Mark up a draft with suggested edits.",
    prefill: "Redline this draft:\n\n",
    persona: "drafting",
  },
];

function makeComposer(focused: boolean): HTMLTextAreaElement {
  // Provide an element matching the SlashMenu focus guard
  // (`#composer-message` textarea). Each test gets a fresh one;
  // the `afterEach` hook below removes them + the focus state.
  const ta = document.createElement("textarea");
  ta.id = "composer-message";
  document.body.appendChild(ta);
  if (focused) ta.focus();
  return ta;
}

describe("<SlashMenu>", () => {
  afterEach(() => {
    // Drop any composer-message textareas left over from a test.
    for (const node of document.querySelectorAll("#composer-message")) {
      node.remove();
    }
    // jsdom keeps `activeElement` pointing at a detached node otherwise.
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  });

  it("renders nothing when open=false", () => {
    const { container } = render(
      <SlashMenu skills={SKILLS} query="" open={false} onPick={vi.fn()} onClose={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders all skills when query is empty", () => {
    render(<SlashMenu skills={SKILLS} query="" open={true} onPick={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText("Search corpus")).toBeTruthy();
    expect(screen.getByText("Redline")).toBeTruthy();
  });

  it("filters skills by id / name / description", () => {
    render(
      <SlashMenu skills={SKILLS} query="red" open={true} onPick={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.queryByText("Search corpus")).toBeNull();
    expect(screen.getByText("Redline")).toBeTruthy();
  });

  it("renders an empty-state message when no skills match", () => {
    render(
      <SlashMenu skills={SKILLS} query="nomatch" open={true} onPick={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.getByText(/No skills match/)).toBeTruthy();
  });

  it("mouse-down on a skill row fires onPick", () => {
    const onPick = vi.fn();
    render(<SlashMenu skills={SKILLS} query="" open={true} onPick={onPick} onClose={vi.fn()} />);
    fireEvent.mouseDown(screen.getByText("Search corpus"));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(SKILLS[0]);
  });

  // ── B1 fixes — keydown guard ─────────────────────────────────────
  it("Enter on document is IGNORED when composer textarea is not focused", () => {
    // Composer exists but NOT focused. The user is somewhere else
    // (a side panel, an export menu) — pressing Enter must not pick
    // a skill behind their back.
    makeComposer(false);
    const onPick = vi.fn();
    render(<SlashMenu skills={SKILLS} query="" open={true} onPick={onPick} onClose={vi.fn()} />);
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onPick).not.toHaveBeenCalled();
  });

  it("Enter on document picks the active skill when composer IS focused", () => {
    makeComposer(true);
    const onPick = vi.fn();
    render(<SlashMenu skills={SKILLS} query="" open={true} onPick={onPick} onClose={vi.fn()} />);
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith(SKILLS[0]);
  });

  it("Escape on document closes the menu when composer is focused", () => {
    makeComposer(true);
    const onClose = vi.fn();
    render(<SlashMenu skills={SKILLS} query="" open={true} onPick={vi.fn()} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape on document is IGNORED when composer is NOT focused", () => {
    makeComposer(false);
    const onClose = vi.fn();
    render(<SlashMenu skills={SKILLS} query="" open={true} onPick={vi.fn()} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });
});
