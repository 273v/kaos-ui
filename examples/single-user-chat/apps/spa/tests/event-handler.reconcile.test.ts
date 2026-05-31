// Regression net for the turn-lifecycle redesign (2026-05-31).
//
// These tests pin the CLIENT half of the "~50% follow-up message flashes
// and disappears" fix: a background history refetch must reconcile into
// the transcript reducer WITHOUT ever deleting an in-flight / just-sent
// optimistic row or a terminal error row. The old reset effect did
// `setState({ ...initialState, messages: serverHistory })`, which wiped
// exactly those rows when the refetch resolved before the server had
// persisted the new turn — the root cause of the disappearing follow-up.
//
// They are deterministic by construction: `reconcileServerHistory` and
// `truncateFrom` are pure functions, so there is no timing/flake surface.

import {
  applyEvent,
  type ChatMessage,
  initialState,
  pushUserAndAssistantPlaceholder,
  reconcileServerHistory,
  type TranscriptState,
  truncateFrom,
} from "@273v/kaos-ui-react/lib";
import { describe, expect, it } from "vitest";

/** A settled server row as the history endpoint would return it. */
function serverRow(id: string, role: "user" | "assistant", content: string): ChatMessage {
  return { id, role, content, created_at: 1, streaming: false };
}

/** Seed a reducer state holding one completed (server-origin) turn. */
function withOneServerTurn(): TranscriptState {
  return reconcileServerHistory(initialState, [
    serverRow("s-u1", "user", "first question"),
    serverRow("s-a1", "assistant", "first answer"),
  ]);
}

describe("reconcileServerHistory — follow-up send race", () => {
  it("preserves an IN-FLIGHT follow-up when a racing refetch lacks it (the bug)", () => {
    // Prior turn is settled from the server.
    let state = withOneServerTurn();
    expect(state.messages).toHaveLength(2);

    // User sends a follow-up: optimistic user + streaming assistant,
    // both tagged with the same clientKey.
    state = pushUserAndAssistantPlaceholder(state, "second question", "ck-2").state;
    expect(state.messages).toHaveLength(4);
    expect(state.pending).toBe(true);

    // A history refetch (the turn-completion / +1200ms / focus refetch)
    // resolves BEFORE the new turn is persisted — server still only
    // knows about turn 1. Pre-fix, this wiped the optimistic follow-up.
    const racingServerHistory = [
      serverRow("s-u1", "user", "first question"),
      serverRow("s-a1", "assistant", "first answer"),
    ];
    const reconciled = reconcileServerHistory(state, racingServerHistory);

    // The in-flight user row AND its streaming assistant placeholder
    // MUST survive — that is the whole fix.
    const contents = reconciled.messages.map((m) => m.content);
    expect(contents).toContain("second question");
    const streaming = reconciled.messages.find((m) => m.streaming === true);
    expect(streaming).toBeTruthy();
    // No duplication of the settled prefix.
    expect(reconciled.messages.filter((m) => m.content === "first answer")).toHaveLength(1);
    expect(reconciled.messages).toHaveLength(4);
  });

  it("preserves a JUST-COMPLETED follow-up while the server is still persisting it (draining window)", () => {
    // The draining-window flicker: a follow-up turn has finished
    // streaming (streaming=false) but the backend's post-stream persist
    // hasn't landed, so a focus / completion refetch resolves with a
    // server snapshot that still lacks the turn. It must NOT vanish.
    let state = withOneServerTurn();
    // Optimistic follow-up whose stream has COMPLETED (not streaming).
    state = pushUserAndAssistantPlaceholder(state, "second question", "ck-2").state;
    state = {
      ...state,
      pending: false,
      messages: state.messages.map((m) =>
        m.clientKey === "ck-2" && m.role === "assistant"
          ? { ...m, streaming: false, content: "second answer" }
          : m,
      ),
    };

    // Server still only knows turn 1 (persist draining).
    const reconciled = reconcileServerHistory(state, [
      serverRow("s-u1", "user", "first question"),
      serverRow("s-a1", "assistant", "first answer"),
    ]);
    const contents = reconciled.messages.map((m) => m.content);
    expect(contents).toContain("second question");
    expect(contents).toContain("second answer");
    expect(reconciled.messages).toHaveLength(4);

    // Once the server catches up, the optimistic tail is absorbed (no dup).
    const caughtUp = reconcileServerHistory(reconciled, [
      serverRow("s-u1", "user", "first question"),
      serverRow("s-a1", "assistant", "first answer"),
      serverRow("s-u2", "user", "second question"),
      serverRow("s-a2", "assistant", "second answer"),
    ]);
    expect(caughtUp.messages).toHaveLength(4);
    expect(caughtUp.messages.filter((m) => m.content === "second question")).toHaveLength(1);
    expect(caughtUp.messages.every((m) => m.origin === "server")).toBe(true);
  });

  it("preserves a terminal error row across a refetch", () => {
    let state = withOneServerTurn();
    // Inject a run_error (e.g. a transient SSE failure) — it renders a
    // banner the user must see; a refetch must not silently erase it.
    state = applyEvent(state, {
      type: "run_error",
      what: "Stream failed.",
      how_to_fix: "Reload if it's stuck.",
    });
    const errorRow = state.messages.find((m) => m.role === "error");
    expect(errorRow).toBeTruthy();

    const reconciled = reconcileServerHistory(state, [
      serverRow("s-u1", "user", "first question"),
      serverRow("s-a1", "assistant", "first answer"),
    ]);
    expect(reconciled.messages.some((m) => m.role === "error")).toBe(true);
  });

  it("adopts the server snapshot for settled turns (cold hydration)", () => {
    const seeded = reconcileServerHistory(initialState, [
      serverRow("s-u1", "user", "q1"),
      serverRow("s-a1", "assistant", "a1"),
    ]);
    expect(seeded.messages).toHaveLength(2);
    expect(seeded.messages.every((m) => m.origin === "server")).toBe(true);
  });

  it("adopts a SHORTER server snapshot (edit-prior / regenerate truncation) for settled rows", () => {
    // Two settled turns locally...
    const state = reconcileServerHistory(initialState, [
      serverRow("s-u1", "user", "q1"),
      serverRow("s-a1", "assistant", "a1"),
      serverRow("s-u2", "user", "q2"),
      serverRow("s-a2", "assistant", "a2"),
    ]);
    // ...server rewound to one turn (edit-prior PATCH truncated it).
    const reconciled = reconcileServerHistory(state, [
      serverRow("s-u1", "user", "q1"),
      serverRow("s-a1", "assistant", "a1"),
    ]);
    expect(reconciled.messages).toHaveLength(2);
    expect(reconciled.messages.map((m) => m.content)).toEqual(["q1", "a1"]);
  });

  it("is idempotent: reconciling the same history twice equals once", () => {
    const base = withOneServerTurn();
    const once = reconcileServerHistory(base, [
      serverRow("s-u1", "user", "first question"),
      serverRow("s-a1", "assistant", "first answer"),
    ]);
    const twice = reconcileServerHistory(once, [
      serverRow("s-u1", "user", "first question"),
      serverRow("s-a1", "assistant", "first answer"),
    ]);
    expect(twice.messages).toEqual(once.messages);
  });
});

describe("truncateFrom — edit-prior / regenerate local truncation", () => {
  it("drops the target message and everything after it", () => {
    const state = reconcileServerHistory(initialState, [
      serverRow("s-u1", "user", "q1"),
      serverRow("s-a1", "assistant", "a1"),
      serverRow("s-u2", "user", "q2"),
      serverRow("s-a2", "assistant", "a2"),
    ]);
    const truncated = truncateFrom(state, "s-u2");
    expect(truncated.messages.map((m) => m.id)).toEqual(["s-u1", "s-a1"]);
  });

  it("is a no-op for an unknown id", () => {
    const state = withOneServerTurn();
    expect(truncateFrom(state, "does-not-exist").messages).toHaveLength(2);
  });
});
