/**
 * <SessionListItem> rename / star / archive flows — pins POL-D.
 *
 * The component depends on TanStack Router (for <Link>) and on
 * usePatchMeta / useArchiveSession (TanStack Query mutations). We mock
 * both so the test stays unit-scoped: the focus here is the keyboard
 * + click affordances + correct mutation payloads, not router
 * navigation.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const patchMutate = vi.fn();
const archiveMutate = vi.fn();

vi.mock("@/hooks/use-patch-meta", () => ({
  usePatchMeta: () => ({ mutate: patchMutate, isPending: false }),
}));
vi.mock("@/hooks/use-archive-session", () => ({
  useArchiveSession: () => ({ mutate: archiveMutate, isPending: false }),
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, ...rest }: { children: ReactNode; [k: string]: unknown }) => (
    <a href="#" {...rest}>
      {children}
    </a>
  ),
}));

import { SessionListItem } from "@/components/sessions/SessionListItem";
import type { SessionSummary } from "@/lib/api-types";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function makeSession(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "01HX0000000000000000000000",
    title: "Cheese regulations Q&A",
    model: "anthropic:claude-haiku-4-5",
    last_message_at: "2026-05-14T17:00:00Z",
    created_at: "2026-05-14T16:00:00Z",
    message_count: 6,
    archived: false,
    starred: false,
    title_source: "auto",
    ...overrides,
  };
}

describe("<SessionListItem>", () => {
  it("renders the title + message-count pill when count > 0", () => {
    wrap(<SessionListItem session={makeSession()} active={false} />);
    expect(screen.getByText("Cheese regulations Q&A")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
  });

  it("hides the message-count pill when count is 0", () => {
    wrap(<SessionListItem session={makeSession({ message_count: 0 })} active={false} />);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("toggles the star via usePatchMeta", () => {
    patchMutate.mockClear();
    wrap(<SessionListItem session={makeSession({ starred: false })} active={false} />);
    fireEvent.click(screen.getByLabelText("Star session"));
    expect(patchMutate).toHaveBeenCalledWith({ starred: true });
  });

  it("un-stars when currently starred", () => {
    patchMutate.mockClear();
    wrap(<SessionListItem session={makeSession({ starred: true })} active={false} />);
    fireEvent.click(screen.getByLabelText("Unstar session"));
    expect(patchMutate).toHaveBeenCalledWith({ starred: false });
  });

  it("renames via menu → input → Enter", () => {
    patchMutate.mockClear();
    wrap(<SessionListItem session={makeSession()} active={false} />);

    fireEvent.click(screen.getByLabelText("Session menu"));
    fireEvent.click(screen.getByRole("menuitem", { name: /rename/i }));

    const input = screen.getByDisplayValue("Cheese regulations Q&A");
    fireEvent.change(input, { target: { value: "Cheese rule survey" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(patchMutate).toHaveBeenCalledWith({ title: "Cheese rule survey" });
  });

  it("rename cancels via Esc without firing a mutation", () => {
    patchMutate.mockClear();
    wrap(<SessionListItem session={makeSession()} active={false} />);

    fireEvent.click(screen.getByLabelText("Session menu"));
    fireEvent.click(screen.getByRole("menuitem", { name: /rename/i }));

    const input = screen.getByDisplayValue("Cheese regulations Q&A");
    fireEvent.change(input, { target: { value: "Discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(patchMutate).not.toHaveBeenCalled();
  });

  it("doesn't fire a patch when the new title is unchanged", () => {
    patchMutate.mockClear();
    wrap(<SessionListItem session={makeSession()} active={false} />);

    fireEvent.click(screen.getByLabelText("Session menu"));
    fireEvent.click(screen.getByRole("menuitem", { name: /rename/i }));

    const input = screen.getByDisplayValue("Cheese regulations Q&A");
    fireEvent.keyDown(input, { key: "Enter" });

    expect(patchMutate).not.toHaveBeenCalled();
  });

  it("archives via menu", () => {
    archiveMutate.mockClear();
    const session = makeSession();
    wrap(<SessionListItem session={session} active={false} />);
    fireEvent.click(screen.getByLabelText("Session menu"));
    fireEvent.click(screen.getByRole("menuitem", { name: /archive/i }));
    expect(archiveMutate).toHaveBeenCalledWith(session.id);
  });
});
