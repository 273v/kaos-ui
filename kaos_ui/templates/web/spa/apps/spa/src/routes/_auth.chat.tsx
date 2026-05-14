// Single-thread chat — consumes @273v/kaos-ui-react for the streaming
// hook + presentational components. The package owns the SSE wire
// surface (15 KaosAgentEvent variants + the span subject×phase
// cartesian) so this template stays decoupled from kaos-agents'
// internal event names.
//
// Backend wire: POST /v1/sessions/{id}/messages (kaos-agents bundled
// API mounted at create_agent_app()). The session id is hardcoded
// "spa-default" for this template — see the single-user-chat example
// in the kaos-ui repo for the full multi-session shape (sidebar,
// rename, archive, history hydration, per-turn metadata sidecars).

import { Composer, Message, TurnStatus } from "@273v/kaos-ui-react/chat";
import { useSendMessage } from "@273v/kaos-ui-react/hooks";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/chat/EmptyState";

export const Route = createFileRoute("/_auth/chat")({
  component: ChatPage,
});

function ChatPage() {
  const stream = useSendMessage({ sessionId: "spa-default" });
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on every messages update IF the user was
  // already near-bottom. Don't yank them away from a passage they
  // are reading. Threshold: 80 px.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run on every messages tick to stick to bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distFromBottom < 80) {
      el.scrollTop = el.scrollHeight;
    }
  }, [stream.state.messages, stream.state.status, stream.state.pending]);

  function onSubmit() {
    const trimmed = input.trim();
    if (!trimmed || stream.state.pending) return;
    void stream.send(trimmed);
    setInput("");
  }

  function onSelectStarter(prompt: string) {
    void stream.send(prompt);
  }

  // Empty state owns its own composer (centered hero). Once the first
  // message lands we switch to the threaded view with a sticky-bottom
  // composer.
  if (stream.state.messages.length === 0) {
    return (
      <EmptyState
        composerValue={input}
        onComposerChange={setInput}
        onSubmit={onSubmit}
        onSelectStarter={onSelectStarter}
        pending={stream.state.pending}
      />
    );
  }

  return (
    <div className="mx-auto flex h-screen w-full max-w-3xl flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 pb-6 pt-12">
        <div className="space-y-6">
          {stream.state.messages.map((m) => (
            <Message key={m.id} message={m} />
          ))}
          <TurnStatus status={stream.state.status} />
        </div>
      </div>
      <div className="border-t border-border bg-background/95 px-6 py-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto max-w-3xl">
          <Composer
            value={input}
            onChange={setInput}
            onSubmit={onSubmit}
            onStop={stream.abort}
            pending={stream.state.pending}
          />
        </div>
      </div>
    </div>
  );
}
