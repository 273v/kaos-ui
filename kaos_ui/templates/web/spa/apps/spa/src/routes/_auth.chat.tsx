import { createFileRoute } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { readSseStream } from "@/lib/streaming";

export const Route = createFileRoute("/_auth/chat")({
  component: ChatPage,
});

function ChatPage() {
  const [messages, setMessages] = useState<Array<{ role: string; text: string }>>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!input.trim() || pending) return;
    const userMsg = input;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: userMsg }]);
    setPending(true);

    let assistant = "";
    setMessages((m) => [...m, { role: "agent", text: "" }]);
    try {
      const sessionId = "spa-default";
      for await (const event of readSseStream(
        `/v1/sessions/${sessionId}/messages`,
        {
          method: "POST",
          body: JSON.stringify({ message: userMsg }),
        },
      )) {
        // kaos-agents wire events use ``content`` for incremental
        // token deltas (text_delta events) and ``text`` for the
        // assembled final on turn_complete. Stream the deltas so
        // tokens land as they arrive; turn_complete is redundant
        // for a streaming UI.
        const data = event.data as Record<string, unknown> | undefined;
        const isDelta = data?.type === "text_delta";
        const piece =
          isDelta && typeof data?.content === "string" ? (data.content as string) : "";
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

  return (
    <div className="mx-auto flex h-screen w-full max-w-3xl flex-col gap-4 py-6">
      <h1 className="text-xl font-semibold">Chat</h1>
      <div className="flex-1 space-y-3 overflow-y-auto rounded-md border border-border p-4">
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">Type a message and press Enter.</p>
        ) : (
          messages.map((m, i) => (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: messages are append-only here
              key={i}
              className={
                m.role === "user"
                  ? "rounded-md bg-primary/10 p-2 text-sm"
                  : m.role === "error"
                    ? "rounded-md bg-red-50 p-2 text-sm text-red-700"
                    : "rounded-md bg-muted p-2 text-sm"
              }
            >
              <div className="text-xs font-semibold uppercase text-muted-foreground">
                {m.role}
              </div>
              <div className="mt-1 whitespace-pre-wrap">{m.text}</div>
            </div>
          ))
        )}
      </div>
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything…"
          className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
