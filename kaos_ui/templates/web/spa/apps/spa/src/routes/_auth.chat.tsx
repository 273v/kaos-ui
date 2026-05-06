import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { Composer } from "@/components/chat/Composer";
import { EmptyState } from "@/components/chat/EmptyState";
import { Message, type MessageRole } from "@/components/chat/Message";
import { readSseStream } from "@/lib/streaming";

export const Route = createFileRoute("/_auth/chat")({
  component: ChatPage,
});

interface ChatMessage {
  role: MessageRole;
  text: string;
}

function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);

  async function send(messageText: string) {
    const trimmed = messageText.trim();
    if (!trimmed || pending) return;

    setMessages((m) => [...m, { role: "user", text: trimmed }]);
    setInput("");
    setPending(true);

    let assistant = "";
    setMessages((m) => [...m, { role: "agent", text: "" }]);

    try {
      const sessionId = "spa-default";
      for await (const event of readSseStream(`/v1/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ message: trimmed }),
      })) {
        // kaos-agents emits incremental tokens on `text_delta` events
        // with the chunk in `data.content`. `turn_complete` carries
        // the assembled final in `data.text` (redundant for streaming).
        const data = event.data as Record<string, unknown> | undefined;
        const isDelta = data?.type === "text_delta";
        const piece = isDelta && typeof data?.content === "string" ? (data.content as string) : "";
        if (piece) {
          assistant += piece;
          setMessages((m) => {
            const next = m.slice(0, -1);
            return [...next, { role: "agent", text: assistant }];
          });
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "stream failed";
      setMessages((m) => [...m.slice(0, -1), { role: "error", text: message }]);
    } finally {
      setPending(false);
    }
  }

  function onSubmit() {
    void send(input);
  }

  function onSelectStarter(prompt: string) {
    void send(prompt);
  }

  // Empty state owns its own composer (centered, hero-style). Once the
  // first message lands, we switch to the threaded view with a
  // sticky-bottom composer.
  if (messages.length === 0) {
    return (
      <EmptyState
        composerValue={input}
        onComposerChange={setInput}
        onSubmit={onSubmit}
        onSelectStarter={onSelectStarter}
        pending={pending}
      />
    );
  }

  return (
    <div className="mx-auto flex h-screen w-full max-w-3xl flex-col">
      {/* Scrolling message column. flex-1 with overflow keeps the
       *  composer pinned at the bottom regardless of message count. */}
      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-12">
        <div className="space-y-6">
          {messages.map((m, i) => (
            <Message
              // biome-ignore lint/suspicious/noArrayIndexKey: append-only list
              key={i}
              role={m.role}
              text={m.text}
              streaming={pending && i === messages.length - 1 && m.role === "agent"}
            />
          ))}
        </div>
      </div>
      <div className="border-t border-border bg-background/95 px-6 py-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto max-w-3xl">
          <Composer value={input} onChange={setInput} onSubmit={onSubmit} pending={pending} />
        </div>
      </div>
    </div>
  );
}
