// Chat detail route. Wires the streaming hook + composer + transcript +
// settings sheet + per-session model override.

import {
  CitationsPanel,
  Composer,
  DocumentExplorer,
  DropZone,
  FileChips,
  Message,
  TurnStatus,
} from "@273v/kaos-ui-react/chat";
import { RunInspector } from "@273v/kaos-ui-react/debug";
import {
  useBackfillFiles,
  useCitations,
  useDeleteFile,
  useLocalStorage,
  useSendMessage,
  useSessionFiles,
  useUploadFile,
} from "@273v/kaos-ui-react/hooks";
import { type ChatMessage, newId } from "@273v/kaos-ui-react/lib";
import { createFileRoute } from "@tanstack/react-router";
import { Bug, Download, FileText, Quote, Settings, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { z } from "zod";

import { ModelPickerChip } from "@/components/settings/ModelPickerChip";
import { SettingsSheet } from "@/components/settings/SettingsSheet";
import { usePatchMeta } from "@/hooks/use-patch-meta";
import { usePatchToolSet } from "@/hooks/use-patch-tool-set";
import { useSession } from "@/hooks/use-session";
import { useSessionMessages } from "@/hooks/use-session-messages";
import { apiFetch } from "@/lib/api-fetch";
import { downloadJSON, downloadMarkdown } from "@/lib/transcript";

import type { CapabilityDecision } from "@273v/kaos-ui-react/chat";

const SearchSchema = z.object({
  debug: z
    .union([z.literal("true"), z.literal(true), z.literal("false"), z.literal(false)])
    .optional(),
  // Prefill the composer when the route mounts. The Welcome page's
  // capability cards land here with prefill set; the user can edit
  // before pressing send. Cleared from URL on first read so refresh
  // doesn't re-prefill.
  prefill: z.string().max(4000).optional(),
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
  const upload = useUploadFile(id);
  const files = useSessionFiles(id);
  const removeFile = useDeleteFile(id);
  const backfill = useBackfillFiles(id);
  const patchToolSet = usePatchToolSet(id);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const onAttach = (file: File) => {
    setUploadError(null);
    upload.mutate(file, {
      onError: (err: unknown) => {
        const what =
          typeof err === "object" && err !== null && "what" in err
            ? String((err as { what: unknown }).what)
            : "Upload failed.";
        setUploadError(what);
      },
    });
  };

  // Map the wire shape `{role, content, added_at, tool_calls}` to our
  // ChatMessage. tool_calls only populate for assistant turns that ran
  // tools; the backend hydrates them from the per-turn .toolcalls.jsonl
  // sidecars we tee off the live SSE stream.
  const initialMessages = useMemo<ChatMessage[]>(() => {
    if (!history.data) return [];
    return history.data.messages.map((m) => ({
      id: newId(),
      role: m.role === "system" ? "system" : m.role,
      content: m.content,
      created_at: m.added_at * 1000,
      streaming: false,
      tool_calls:
        m.tool_calls && m.tool_calls.length > 0
          ? m.tool_calls.map((tc) => ({
              id: tc.id,
              name: tc.name,
              status: tc.status,
              args_preview: tc.args_preview ?? undefined,
              result_preview: tc.result_preview ?? undefined,
            }))
          : undefined,
    }));
  }, [history.data]);

  const stream = useSendMessage({ sessionId: id, initialMessages });
  const citations = useCitations(id, stream.state.messages);

  const search = Route.useSearch();
  const navigateRoute = Route.useNavigate();
  const debugDefault = search.debug === "true" || search.debug === true;
  const [input, setInput] = useState(search.prefill ?? "");

  // Clear the prefill param from the URL on first mount so refresh
  // doesn't re-prefill (and so the URL stays scannable).
  useEffect(() => {
    if (search.prefill) {
      void navigateRoute({
        search: (prev) => ({ ...prev, prefill: undefined }),
        replace: true,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [citationsOpen, setCitationsOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(debugDefault);
  // Persisted preference: once the user flips verbose tools on, it
  // stays on across reloads + new sessions. Keyed under a stable
  // string so a future "global UI prefs" page can introspect it.
  const [verboseTools, setVerboseTools] = useLocalStorage("kaos:verbose-tools", false);

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

  // Pin auto-elevated groups into the session's persistent ceiling.
  // The ElevationPill's "Pin to session" affordance calls this with
  // the deduped groups the AgenticLoop widened to during this turn.
  const onPinElevationToSession = (groups: string[]) => {
    if (!session.data || groups.length === 0) return;
    const current = new Set(session.data.policy.allowed_groups);
    for (const g of groups) current.add(g);
    if (current.size === session.data.policy.allowed_groups.length) return;
    patchToolSet.mutate({ allowed_groups: Array.from(current).sort() });
  };

  // Yellow-confirm capability resolution. The AgenticLoop fires the
  // event but doesn't actually pause (post-0.1.0a3 the loop is
  // fire-and-continue); the SPA renders the card so the user can
  // choose to PERSIST the elevation. Until a backend resume route
  // exists, the four actions resolve as:
  //   - enable_turn:     dismiss the card (no-op; loop already ran)
  //   - enable_session:  persist the groups into allowed_groups
  //   - deny_continue:   dismiss the card
  //   - deny_stop:       dismiss + abort any active stream
  const onCapabilityDecide = (decision: CapabilityDecision, groups: string[]) => {
    if (decision === "enable_session") {
      onPinElevationToSession(groups);
    }
    if (decision === "deny_stop") {
      stream.abort();
    }
    // All four decisions clear the per-message capability_request snapshot
    // so the card unmounts. The reducer leaves `pending` alone so the
    // streaming message can keep accumulating text deltas if any are
    // still arriving.
    // (We don't mutate state directly here — Message's local-clear
    // affordance + the next loop_terminated event handle visibility.)
  };

  const meta = session.data;
  return (
    <div className="flex h-full">
      <div className="flex flex-1 min-w-0 flex-col">
        <header className="border-b border-border px-6 py-3.5 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <h1
              className="font-serif text-lg leading-tight truncate text-foreground"
              title={meta?.title}
            >
              {meta?.title ?? "Loading…"}
            </h1>
            {meta && (
              <p className="text-xs text-foreground/70 tabular-nums mt-0.5">
                <span className="font-mono">{meta.model}</span>
                <span className="mx-1.5 text-foreground/40">·</span>
                {meta.message_count} {meta.message_count === 1 ? "message" : "messages"}
                {meta.tools_enabled && (
                  <>
                    <span className="mx-1.5 text-foreground/40">·</span>
                    tools on
                  </>
                )}
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
            onClick={() => setDocsOpen((v) => !v)}
            disabled={!meta}
            className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40 ${
              docsOpen ? "bg-muted text-foreground" : ""
            }`}
            title={
              files.data && files.data.files.length > 0
                ? `${files.data.files.length} documents`
                : "Documents"
            }
            aria-label="Toggle documents panel"
            aria-pressed={docsOpen}
          >
            <FileText className="h-3.5 w-3.5" />
            {files.data && files.data.files.length > 0 && (
              <span className="tabular-nums text-[10px]">{files.data.files.length}</span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setCitationsOpen((v) => !v)}
            disabled={!meta}
            className={
              "inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40 " +
              (citationsOpen ? "bg-muted text-foreground" : "")
            }
            title={citations.total > 0 ? `${citations.total} citations` : "Citations"}
            // Accessible name MUST include the visible badge text
            // (WCAG 2.5.3 Label in Name) — Lighthouse flagged this
            // when the count badge "4" appeared but the aria-label
            // didn't reference it.
            aria-label={
              citations.total > 0
                ? `Citations (${citations.total})`
                : "Citations"
            }
            aria-pressed={citationsOpen}
          >
            <Quote className="h-3.5 w-3.5" />
            {citations.total > 0 && (
              <span className="tabular-nums text-[10px]">{citations.total}</span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setVerboseTools((v) => !v)}
            disabled={!meta}
            className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40 ${
              verboseTools ? "bg-muted text-foreground" : ""
            }`}
            title={
              verboseTools ? "Tool details expanded by default" : "Show tool details by default"
            }
            aria-label="Toggle verbose tool details"
            aria-pressed={verboseTools}
          >
            <Wrench className="h-3.5 w-3.5" />
          </button>

          <button
            type="button"
            onClick={() => setInspectorOpen((v) => !v)}
            disabled={!meta}
            className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40 ${
              inspectorOpen ? "bg-muted text-foreground" : ""
            }`}
            title="Run inspector (live cost / events / JSON tree)"
            aria-label="Toggle run inspector"
            aria-pressed={inspectorOpen}
          >
            <Bug className="h-3.5 w-3.5" />
          </button>

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
                <p className="text-sm text-muted-foreground">
                  Send a message below to get started.
                </p>
              </div>
            )}

            <div className="space-y-1 divide-y divide-border/60">
              {stream.state.messages.map((m) => (
                <Message
                  key={m.id}
                  message={m}
                  verboseTools={verboseTools}
                  onPinElevationToSession={onPinElevationToSession}
                  onCapabilityDecide={onCapabilityDecide}
                />
              ))}
            </div>

            <TurnStatus status={stream.state.status} />
          </div>
        </div>

        <DropZone onDrop={onAttach} disabled={!meta} />

        {uploadError && (
          <div className="mx-auto max-w-3xl px-4">
            <div
              role="alert"
              className="mb-2 flex items-start justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
            >
              <span>{uploadError}</span>
              <button
                type="button"
                onClick={() => setUploadError(null)}
                className="text-destructive/70 hover:text-destructive text-xs"
                aria-label="Dismiss upload error"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {files.data && files.data.files.length > 0 && (
          <div className="mx-auto max-w-3xl px-4">
            <FileChips
              files={files.data.files}
              onRemove={(name) => removeFile.mutate(name)}
              removing={
                removeFile.variables && removeFile.isPending
                  ? new Set([removeFile.variables])
                  : undefined
              }
              maxVisible={3}
              onShowAll={() => setDocsOpen(true)}
            />
          </div>
        )}

        <Composer
          value={input}
          onChange={setInput}
          onSubmit={onSubmit}
          onStop={stream.abort}
          pending={stream.state.pending}
          placeholder={`Message ${meta?.title ?? "this conversation"}…`}
          onAttach={onAttach}
          uploading={upload.isPending}
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

        <RunInspector
          events={stream.rawEvents}
          open={inspectorOpen}
          onClose={() => setInspectorOpen(false)}
        />
      </div>

      <DocumentExplorer
        open={docsOpen}
        onClose={() => setDocsOpen(false)}
        files={files.data?.files ?? []}
        loading={files.isLoading}
        onBackfill={() => backfill.mutate({})}
        backfilling={backfill.isPending}
        onResummarize={(filename) => backfill.mutate({ filename, overwrite: true })}
        resummarizing={
          backfill.isPending && backfill.variables?.filename
            ? new Set([backfill.variables.filename])
            : undefined
        }
        onDownload={async (filename) => {
          // Authenticated fetch → blob → trigger save. A plain <a href>
          // wouldn't attach the bearer token (the browser doesn't
          // carry it for top-level navigations / downloads under our
          // localStorage-token auth model), so the request would 401.
          const path = `/v1/chat/sessions/${encodeURIComponent(id)}/files/${encodeURIComponent(filename)}/download`;
          let res: Response;
          try {
            res = await apiFetch(path);
          } catch {
            return;
          }
          if (!res.ok) {
            return;
          }
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }}
      />

      <CitationsPanel
        open={citationsOpen}
        onClose={() => setCitationsOpen(false)}
        byMessage={citations.byMessage}
        pending={citations.pending}
        error={citations.error}
      />
    </div>
  );
}
