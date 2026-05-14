// Chat detail route. Wires the streaming hook + composer + transcript +
// settings sheet + per-session model override.

import { createFileRoute } from "@tanstack/react-router";
import { Download, Settings } from "lucide-react";
import { useMemo, useState } from "react";
import { z } from "zod";

import { Composer } from "@/components/chat/Composer";
import { DebugPanel } from "@/components/chat/DebugPanel";
import { Message } from "@/components/chat/Message";
import { TurnStatus } from "@/components/chat/TurnStatus";
import { ModelPickerChip } from "@/components/settings/ModelPickerChip";
import { SettingsSheet } from "@/components/settings/SettingsSheet";
import { usePatchMeta } from "@/hooks/use-patch-meta";
import { useSendMessage } from "@/hooks/use-send-message";
import { useSession } from "@/hooks/use-session";
import { useSessionMessages } from "@/hooks/use-session-messages";
import type { ChatMessage } from "@/lib/chat-state";
import { newId } from "@/lib/chat-state";
import { downloadJSON, downloadMarkdown } from "@/lib/transcript";

const SearchSchema = z.object({
  debug: z
    .union([z.literal("true"), z.literal(true), z.literal("false"), z.literal(false)])
    .optional(),
});

export const Route = createFileRoute("/_auth/sessions/$id")({
  validateSearch: (search) => SearchSchema.parse(search),
  component: ChatDetail,
});

function ChatDetail() {
  const { id } = Route.useParams();
  const session = useSession(id);
  const history = useSessionMessages(id);
  const patch = usePatchMeta(id);

  // Map the wire shape `{role, content, added_at}` to our ChatMessage.
  const initialMessages = useMemo<ChatMessage[]>(() => {
    if (!history.data) return [];
    return history.data.messages.map((m) => ({
      id: newId(),
      role: m.role === "system" ? "system" : m.role,
      content: m.content,
      created_at: m.added_at * 1000,
      streaming: false,
    }));
  }, [history.data]);

  const stream = useSendMessage({ sessionId: id, initialMessages });

  const [input, setInput] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const onSubmit = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    void stream.send(text);
  };

  const onModelChange = (modelId: string) => {
    if (!session.data || session.data.model === modelId) return;
    patch.mutate({ model: modelId });
  };

  const meta = session.data;
  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-medium truncate" title={meta?.title}>
            {meta?.title ?? "Loading…"}
          </h1>
          {meta && (
            <p className="text-xs text-muted-foreground tabular-nums">
              {meta.model} · {meta.message_count} messages
              {meta.tools_enabled && " · tools on"}
            </p>
          )}
        </div>

        <div className="relative">
          <button
            type="button"
            onClick={() => setExportOpen((v) => !v)}
            disabled={!meta || stream.state.messages.length === 0}
            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40"
            title="Export transcript"
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
          {exportOpen && meta && (
            <div
              role="menu"
              className="absolute right-0 top-9 z-10 bg-card border border-border rounded-md min-w-[180px] py-1 text-sm"
              onMouseLeave={() => setExportOpen(false)}
            >
              <button
                type="button"
                onClick={() => {
                  downloadMarkdown({ meta, messages: stream.state.messages });
                  setExportOpen(false);
                }}
                className="w-full text-left px-3 py-1.5 hover:bg-muted"
              >
                Download Markdown
              </button>
              <button
                type="button"
                onClick={() => {
                  downloadJSON({ meta, messages: stream.state.messages });
                  setExportOpen(false);
                }}
                className="w-full text-left px-3 py-1.5 hover:bg-muted"
              >
                Download JSON
              </button>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          disabled={!meta}
          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40"
          title="Session settings"
          aria-label="Session settings"
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
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
                {meta?.title || "New conversation"}
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
        onStop={stream.abort}
        pending={stream.state.pending}
        placeholder={`Message ${meta?.title ?? "this conversation"}…`}
        leftChips={
          meta && (
            <ModelPickerChip
              value={meta.model}
              onChange={onModelChange}
              disabled={stream.state.pending}
            />
          )
        }
      />

      {meta && (
        <SettingsSheet open={settingsOpen} onClose={() => setSettingsOpen(false)} meta={meta} />
      )}

      <DebugPanel events={stream.rawEvents} />
    </div>
  );
}
