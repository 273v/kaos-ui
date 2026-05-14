import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { Composer } from "@/components/chat/Composer";
import { EmptyState } from "@/components/chat/EmptyState";
import { Message, type MessageRole } from "@/components/chat/Message";
import { TurnStatus, type TurnStatusValue } from "@/components/chat/TurnStatus";
import { UsageChip } from "@/components/chat/UsageChip";
import { readSseStream } from "@/lib/streaming";

export const Route = createFileRoute("/_auth/chat")({
  component: ChatPage,
});

interface ChatMessage {
  role: MessageRole;
  text: string;
  /** Populated by `usage_observed` / `turn_complete` so we can render
   *  a tokens + cost chip under finalized assistant messages. */
  usage?: { tokens?: number; costUsd?: number };
}

function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState<TurnStatusValue | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on every message update IF the user was
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
  }, [messages, status, pending]);

  async function send(messageText: string) {
    const trimmed = messageText.trim();
    if (!trimmed || pending) return;

    setMessages((m) => [...m, { role: "user", text: trimmed }]);
    setInput("");
    setPending(true);
    setStatus({ kind: "info", text: "Thinking…" });

    let assistant = "";
    let lastUsage: { tokens?: number; costUsd?: number } | undefined;
    setMessages((m) => [...m, { role: "agent", text: "" }]);

    try {
      const sessionId = "spa-default";
      for await (const event of readSseStream(`/v1/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ message: trimmed }),
      })) {
        const data = event.data as Record<string, unknown> | undefined;
        const type = data?.type;

        // 1. Streaming token chunks. The kaos-agents canonical field is
        //    `content`, not `text`. (`turn_complete.text` is the full
        //    assembled message, redundant when we accumulate deltas.)
        if (type === "text_delta" && typeof data?.content === "string") {
          // First token cancels the status pill — the user can now
          // SEE the agent generating, no need for a "thinking" hint.
          if (status !== null) setStatus(null);
          assistant += data.content as string;
          setMessages((m) => {
            const next = m.slice(0, -1);
            return [...next, { role: "agent", text: assistant }];
          });
          continue;
        }

        // 2. Lifecycle / status events — set the status pill.
        if (type === "turn_start") {
          setStatus({ kind: "info", text: "Thinking…" });
        } else if (type === "intent_classified") {
          // Transient — replaced quickly by tool_call_start or
          // text_delta. Show only when the intent isn't a plain
          // RESPOND (which means the agent is about to do something
          // heavier than answer in prose).
          const intent = data?.intent as string | undefined;
          if (intent && intent !== "respond") {
            setStatus({ kind: "info", text: `Intent: ${intent}` });
          }
        } else if (type === "tool_call_start") {
          const toolName = (data?.tool_name as string | undefined) ?? "tool";
          setStatus({ kind: "tool", text: `Running ${toolName}…` });
        } else if (type === "tool_call_result") {
          // Brief acknowledgement that the tool returned, then we
          // wait for either another tool call or text_delta.
          setStatus({ kind: "info", text: "Generating response…" });
        } else if (type === "step_start") {
          const desc = (data?.description as string | undefined) ?? "step";
          setStatus({ kind: "info", text: `Step: ${desc}` });
        } else if (type === "run_error") {
          const msg = (data?.message as string | undefined) ?? "Run failed";
          setStatus({ kind: "error", text: msg });
        }

        // 3. Usage accounting — accumulate so we can hang it on the
        //    finalized assistant message.
        if (type === "usage_observed" || type === "turn_complete") {
          const tokens = data?.total_tokens ?? data?.tokens_used;
          const cost = data?.cost_usd;
          if (typeof tokens === "number") {
            lastUsage = { ...lastUsage, tokens };
          }
          if (typeof cost === "number") {
            lastUsage = { ...lastUsage, costUsd: cost };
          }
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "stream failed";
      setMessages((m) => [...m.slice(0, -1), { role: "error", text: message }]);
    } finally {
      // Attach usage to the finalized assistant message and clear
      // transient state.
      if (lastUsage) {
        setMessages((m) => {
          if (m.length === 0) return m;
          const last = m[m.length - 1];
          if (!last || last.role !== "agent") return m;
          return [...m.slice(0, -1), { ...last, usage: lastUsage }];
        });
      }
      setPending(false);
      setStatus(null);
    }
  }

  function onSubmit() {
    void send(input);
  }

  function onSelectStarter(prompt: string) {
    void send(prompt);
  }

  // Empty state owns its own composer (centered hero). Once the first
  // message lands we switch to the threaded view with a sticky-bottom
  // composer.
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
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 pb-6 pt-12">
        <div className="space-y-6">
          {messages.map((m, i) => {
            const isLast = i === messages.length - 1;
            const isStreaming = pending && isLast && m.role === "agent";
            return (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: append-only list
                key={i}
                className="space-y-2"
              >
                <Message role={m.role} text={m.text} streaming={isStreaming} />
                {m.usage && !isStreaming ? (
                  <UsageChip tokens={m.usage.tokens} costUsd={m.usage.costUsd} />
                ) : null}
              </div>
            );
          })}
          {/* Status pill rendered just below the streaming assistant
           *  bubble so the user always knows what the agent is doing. */}
          {pending && status ? (
            <div>
              <TurnStatus status={status} />
            </div>
          ) : null}
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
