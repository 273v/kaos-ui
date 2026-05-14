// Chat detail route. Wires the streaming hook + composer + transcript.

import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Composer } from "@/components/chat/Composer";
import { Message } from "@/components/chat/Message";
import { TurnStatus } from "@/components/chat/TurnStatus";
import { useSendMessage } from "@/hooks/use-send-message";
import { useSession } from "@/hooks/use-session";

export const Route = createFileRoute("/_auth/sessions/$id")({
  component: ChatDetail,
});

function ChatDetail() {
  const { id } = Route.useParams();
  const session = useSession(id);
  const [input, setInput] = useState("");
  const stream = useSendMessage({ sessionId: id });

  const onSubmit = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    void stream.send(text);
  };

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-6 py-3">
        <h1 className="text-sm font-medium truncate" title={session.data?.title}>
          {session.data?.title ?? "Loading…"}
        </h1>
        {session.data && (
          <p className="text-xs text-muted-foreground tabular-nums">
            {session.data.model} · {session.data.message_count} messages
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-6 py-8" role="log" aria-live="polite">
          {stream.state.banners.length > 0 && (
            <div className="mb-4 space-y-2">
              {stream.state.banners.map((b) => (
                <div
                  key={b.id}
                  className={
                    "rounded-md border px-3 py-2 text-sm " +
                    (b.kind === "error"
                      ? "border-destructive/40 text-destructive bg-destructive/5"
                      : "border-border bg-muted text-muted-foreground")
                  }
                >
                  {b.text}
                </div>
              ))}
            </div>
          )}

          {stream.state.messages.length === 0 && (
            <div className="text-center pt-16">
              <h2 className="text-3xl font-serif font-light mb-1">
                {session.data?.title || "New conversation"}
              </h2>
              <p className="text-sm text-muted-foreground">Send a message below to get started.</p>
            </div>
          )}

          <div className="space-y-1 divide-y divide-border/60">
            {stream.state.messages.map((m) => (
              <Message key={m.id} message={m} />
            ))}
          </div>

          <TurnStatus status={stream.state.status} />
        </div>
      </div>

      <Composer
        value={input}
        onChange={setInput}
        onSubmit={onSubmit}
        pending={stream.state.pending}
        placeholder={`Message ${session.data?.title ?? "this conversation"}…`}
      />
    </div>
  );
}
