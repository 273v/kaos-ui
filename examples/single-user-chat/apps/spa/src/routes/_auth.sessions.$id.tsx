// Chat detail route. Wires the streaming hook + composer + transcript +
// settings sheet + per-session model override.

import type { CapabilityDecision } from "@273v/kaos-ui-react/chat";
import {
  CitationsPanel,
  Composer,
  DocumentExplorer,
  DropZone,
  FileChips,
  Message,
  type Skill,
  SlashMenu,
  TurnStatus,
  VfsExplorer,
} from "@273v/kaos-ui-react/chat";
import { RunInspector } from "@273v/kaos-ui-react/debug";
import {
  useActiveRun,
  useBackfillFiles,
  useCitations,
  useDeleteFile,
  useLocalStorage,
  useSendMessage,
  useSessionFiles,
  useSessionVfs,
  useUploadFile,
} from "@273v/kaos-ui-react/hooks";
import { type ChatMessage, newId, stripScratchpadTags } from "@273v/kaos-ui-react/lib";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
  Bug,
  Download,
  FileText,
  FolderTree,
  Maximize2,
  Minimize2,
  Quote,
  Settings,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";
import { ModelPickerChip } from "@/components/settings/ModelPickerChip";
import { PlanActChip } from "@/components/settings/PlanActChip";
import { SettingsSheet } from "@/components/settings/SettingsSheet";
import { usePatchMeta } from "@/hooks/use-patch-meta";
import { usePatchToolSet } from "@/hooks/use-patch-tool-set";
import { useSession } from "@/hooks/use-session";
import { useSessionMessages } from "@/hooks/use-session-messages";
import { apiFetch } from "@/lib/api-fetch";
import { queryKeys } from "@/lib/query-keys";
import { BUILTIN_SKILLS } from "@/lib/skills";
import { downloadJSON, downloadMarkdown } from "@/lib/transcript";

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
  const queryClient = useQueryClient();
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
    // B11 — collapse AgenticLoop replan-iteration duplicates. When
    // `auto_loop=true` and the GoalChecker keeps returning
    // `needs_more_work`, the kaos-agents worker re-runs the user
    // turn N times and appends a fresh `user:` + `assistant:` pair
    // to SessionMemory on EACH iteration. The user typed the
    // message once; we keep only the final user+assistant pair from
    // each consecutive-duplicate group so the transcript reads as
    // one turn per user-typed-message.
    //
    // Architecturally this should land in kaos-agents (the
    // AgenticLoop should own a single memory write per turn), but
    // until that release the SPA does the dedupe so users don't
    // see the same question rendered 3x. `meta.message_count` is
    // already the correct turn count — it only increments by 2 per
    // `run_agentic_turn` call.
    const raw = history.data.messages;
    const deduped: typeof raw = [];
    for (let i = 0; i < raw.length; i++) {
      const cur = raw[i];
      if (!cur) continue;
      if (cur.role === "user") {
        let lastDupIdx = i;
        let j = i + 2;
        while (j < raw.length && raw[j]?.role === "user" && raw[j]?.content === cur.content) {
          lastDupIdx = j;
          j += 2;
        }
        const finalUser = raw[lastDupIdx];
        const finalAsst = raw[lastDupIdx + 1];
        if (finalUser) deduped.push(finalUser);
        if (finalAsst && finalAsst.role === "assistant") deduped.push(finalAsst);
        i = lastDupIdx + (finalAsst?.role === "assistant" ? 1 : 0);
      } else {
        deduped.push(cur);
      }
    }
    return deduped.map((m) => ({
      id: newId(),
      role: m.role === "system" ? "system" : m.role,
      // B10 — strip scratchpad tags (`[/response]`, `<function_calls>`)
      // from historical assistant turns. Sessions created against
      // older kaos-agents (< 0.1.0a5) persisted dirty bytes into
      // session memory; this strip keeps the transcript clean even
      // for those legacy sessions. The live SSE reducer applies the
      // same strip via event-handler.ts.
      content: m.role === "assistant" ? stripScratchpadTags(m.content) : m.content,
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

  // SSE resume (Stage 1): on mount, ask the backend whether this
  // session has an in-flight run; if so, thread the run id into
  // useSendMessage so it opens the GET /runs/{run_id}/events stream
  // instead of waiting for the user to send a fresh message.
  const activeRun = useActiveRun(id);
  const resumeFrom =
    activeRun.data && activeRun.data.status === "running" ? { runId: activeRun.data.run_id } : null;
  const stream = useSendMessage({ sessionId: id, initialMessages, resumeFrom });
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
  }, [search.prefill, navigateRoute]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [citationsOpen, setCitationsOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [vfsOpen, setVfsOpen] = useState(false);
  const [vfsShowSidecars, setVfsShowSidecars] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(debugDefault);
  const vfs = useSessionVfs(id, {
    enabled: vfsOpen,
    includeSidecars: vfsShowSidecars,
  });
  // Persisted preference: once the user flips verbose tools on, it
  // stays on across reloads + new sessions. Keyed under a stable
  // string so a future "global UI prefs" page can introspect it.
  const [verboseTools, setVerboseTools] = useLocalStorage("kaos:verbose-tools", false);
  // #453 — narrow vs wide transcript. Narrow uses the editorial
  // 72ch measure; wide scales with viewport so multi-NDA matrices
  // and CSV-ready tables don't word-wrap claustrophobically.
  const [transcriptWide, setTranscriptWide] = useLocalStorage("kaos:transcript-wide", false);

  // B8 — refresh the session meta + message-history + sidebar list
  // when a turn finishes streaming. Without this, the immediate-
  // heuristic title patch the backend writes on the first turn
  // (and the message_count bump on every turn) doesn't surface in
  // the chat header or the sidebar until the user reloads or
  // switches sessions and back. Trigger fires on the pending
  // true→false edge.
  //
  // UX-A1: also re-invalidate ~1.2s later. The title generator runs
  // as a fire-and-forget background task on the backend; on the first
  // turn it can complete AFTER the SSE stream's terminal event, so
  // the synchronous invalidation we fire on `pending: true→false`
  // refetches /meta before the title is written and the header
  // re-snaps to "Untitled" until the user submits a 2nd turn. The
  // delayed re-invalidation catches that race.
  const wasPendingRef = useRef(false);
  useEffect(() => {
    if (wasPendingRef.current && !stream.state.pending) {
      // Turn-lifecycle redesign (2026-05-31): refresh only the session
      // META (title / message_count) and the sidebar LIST here. We no
      // longer invalidate the message-HISTORY query on turn completion.
      //
      // The `useSendMessage` reducer is the single source of truth for
      // the transcript and ALREADY contains this turn (the optimistic
      // user row + the streamed assistant row). Refetching history on
      // completion was both unnecessary AND harmful: the immediate
      // invalidate fires at stream-end while the canonical-turn persist
      // is still draining, so the refetch could resolve with a server
      // snapshot MISSING the just-finished turn — which the old
      // reset-replace then wiped from the transcript (the "flash and
      // disappear" follow-up bug). History now refetches only on cold
      // load / session switch / window-focus, and is reconciled
      // non-destructively (see `reconcileServerHistory`).
      const invalidateMeta = () => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(id) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      };
      invalidateMeta();
      // The first-turn title is written by the backend's post-stream
      // persist task, which can land AFTER this edge — re-invalidate the
      // META once more so the header/sidebar pick it up. (This no longer
      // touches the transcript, so it cannot wipe anything.)
      const t = setTimeout(invalidateMeta, 1200);
      wasPendingRef.current = stream.state.pending;
      return () => clearTimeout(t);
    }
    wasPendingRef.current = stream.state.pending;
  }, [stream.state.pending, id, queryClient]);

  const onSubmit = () => {
    const text = input.trim();
    if (!text) return;
    // P0 — don't clear the textarea unless we know `send()` will
    // actually fire. The hook silently no-ops when an SSE is in
    // flight (live OR resume), and pre-fix the user would see
    // "textarea cleared, nothing happened" on the post-turn
    // resume-race window. The Send button is also disabled when
    // pending=true, but Enter bypasses the disabled state, so this
    // is the load-bearing guard for keyboard submits.
    if (stream.state.pending) return;
    setInput("");
    void stream.send(text);
  };

  // Slash-menu state. The menu opens when the composer text *starts*
  // with `/` and the user is still editing the first token (no
  // whitespace yet). The query is the substring after the slash.
  const slashOpen =
    input.startsWith("/") && !input.slice(1).includes(" ") && !input.slice(1).includes("\n");
  const slashQuery = slashOpen ? input.slice(1) : "";

  const onPickSkill = (skill: Skill) => {
    // Replace the leading `/<query>` with the skill's prefill text.
    setInput(skill.prefill);
    // Optionally tune the session policy. We don't switch model
    // automatically — the user can pick that themselves from the
    // composer chip — but we DO apply the tool-group ceiling if the
    // skill specifies one, so "Forensics" really locks the egress.
    if (skill.allowed_groups || skill.persona) {
      patchToolSet.mutate({
        allowed_groups: skill.allowed_groups,
        // persona is patched via the policy field on the wire;
        // the SPA's PATCH body only exposes ceiling fields today,
        // so persona requires a follow-up release.
      });
    }
    // Re-focus the composer. If the prefill carries a ``{placeholder}``
    // token, SELECT the first one so the user types over it directly —
    // pre-fix the user could hit Enter and send a literal ``{topic}``
    // to the LLM. Falls back to caret-at-end when no placeholder.
    // The documented ``{cursor}`` marker is honored as a placeholder
    // alias (same behavior).
    setTimeout(() => {
      const ta = document.getElementById("composer-message");
      if (!(ta instanceof HTMLTextAreaElement)) return;
      ta.focus();
      const match = /\{[a-z_][a-z0-9_]*\}/i.exec(ta.value);
      if (match) {
        ta.setSelectionRange(match.index, match.index + match[0].length);
      } else {
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }
    }, 0);
  };

  const onModelChange = (modelId: string) => {
    if (!session.data || session.data.model === modelId) return;
    patch.mutate({ model: modelId });
  };

  // Plan Issue 10 layer 2 — thumbs feedback. POST to the backend's
  // append-only JSONL audit log. Fire-and-forget at the UI layer:
  // the Message component's FeedbackButtons records the sentiment
  // locally for visual confirmation, so we don't need a Promise here.
  // A failed POST is logged to console (not surfaced to the user)
  // because feedback is informational, not load-bearing — we never
  // want a 5xx on feedback to interrupt the chat surface.
  const onFeedback = (messageId: string, value: "up" | "down") => {
    apiFetch(`/v1/chat/sessions/${id}/messages/${messageId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }).catch((err) => {
      console.warn("feedback POST failed", { messageId, value, err });
    });
  };

  // Plan Issue 10 layer 4 — edit a prior user message in place.
  // The backend at app/routers/messages.py:264 takes a numeric
  // ``idx`` pointing at the USER message; it replaces the content
  // and truncates every subsequent item. The client then re-sends
  // the edited user message to trigger a fresh run (the SPA's
  // existing useSendMessage hook owns that send).
  //
  // The handler resolves messageId → array idx via findIndex
  // before PATCHing. Errors are console-warned; the
  // EditPriorButton's 1.5s busy lock suppresses double-clicks.
  const onEditPrior = (messageId: string, newText: string) => {
    const idx = stream.state.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) {
      console.warn("edit-prior: message id not found in transcript", { messageId });
      return;
    }
    apiFetch(`/v1/chat/sessions/${id}/messages/${idx}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newText }),
    })
      .then(() => {
        // Truncate the LOCAL transcript at the edited message — the
        // backend PATCH already rewound SessionMemory at the same index.
        // We do this locally instead of relying on a destructive
        // history-refetch-replace (which we removed because it wiped
        // optimistic follow-ups). Then re-send so the reducer appends
        // the fresh turn. The reducer is the single source of truth.
        stream.truncate(messageId);
        setInput(newText);
        setTimeout(() => {
          const form = document.getElementById("composer-form") as HTMLFormElement | null;
          form?.requestSubmit();
        }, 200);
      })
      .catch((err) => {
        console.warn("edit-prior PATCH failed", { messageId, idx, err });
      });
  };

  // Plan Issue 10 layer 3 — regenerate this assistant turn from the
  // prior user message. The backend at
  // app/routers/messages.py:174 rewinds MESSAGES at index ``idx``
  // (inclusive of the assistant turn at that index) and the client
  // reissues the prior user message via POST /messages to trigger
  // a fresh run with full ChatGPT/Claude.ai parity.
  //
  // The backend uses NUMERIC idx (not message id strings), so the
  // handler maps the clicked ChatMessage.id back to its array index
  // before POSTing. Errors are console-warned; the
  // RegenerateButton's 1.5s busy lock suppresses double-clicks.
  const onRegenerate = (messageId: string) => {
    const idx = stream.state.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) {
      console.warn("regenerate: message id not found in transcript", { messageId });
      return;
    }
    // Drop the stale assistant turn (and anything after) from the local
    // transcript immediately — the backend rewinds SessionMemory at the
    // same index. The fresh run is surfaced by the resume path
    // (`useActiveRun` → `_resumeRun`) once the backend starts it.
    stream.truncate(messageId);
    apiFetch(`/v1/chat/sessions/${id}/messages/${idx}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(() => {
        // Belt-and-suspenders: reflect the server-side rewind+rerun.
        // Turn completion no longer auto-refetches history, so refetch
        // explicitly here (an explicit user action); `reconcileServerHistory`
        // applies it non-destructively (live/streaming rows are kept).
        const refetchHistory = () =>
          void queryClient.invalidateQueries({
            queryKey: [...queryKeys.session(id), "history"],
          });
        refetchHistory();
        setTimeout(refetchHistory, 1500);
      })
      .catch((err) => {
        console.warn("regenerate POST failed", { messageId, idx, err });
      });
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

  // Highlight-to-Ask flow (F.9). When the user selects text inside a
  // doc-explorer summary and clicks the floating "Ask about this"
  // pill, we prefill the composer with a structured passage prompt
  // and focus the chat. The passage is truncated at 600 chars so
  // the composer textarea stays scannable; the full passage is
  // implied by the citation.
  const onAskAboutSelection = ({ filename, passage }: { filename: string; passage: string }) => {
    const MAX_PASSAGE = 600;
    const trimmed = passage.length > MAX_PASSAGE ? `${passage.slice(0, MAX_PASSAGE)}…` : passage;
    const composed = `About this passage from \`${filename}\`:\n\n> ${trimmed.replace(/\n/g, "\n> ")}\n\n`;
    setInput(composed);
    // Defer focus so React commits the textarea value first.
    setTimeout(() => {
      const ta = document.getElementById("composer-message");
      if (ta instanceof HTMLTextAreaElement) {
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }
    }, 0);
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
  const onCapabilityDecide = (
    decision: CapabilityDecision,
    groups: string[],
    messageId: string,
  ) => {
    if (decision === "enable_session") {
      onPinElevationToSession(groups);
    }
    if (decision === "deny_stop") {
      stream.abort();
    }
    // All four decisions clear the per-message capability_request
    // snapshot so the card unmounts. Pre-0.1.0a8 this comment
    // claimed the card relied on `loop_terminated` for visibility,
    // but that event arrives long after the user's choice — leaving
    // the card mounted in the meantime. `clearCapability` flips it
    // off the millisecond the user clicks.
    stream.clearCapability(messageId);
  };

  const meta = session.data;

  // Auto-scroll the transcript on every text delta — but only when the
  // user is already within ~80px of the bottom (mirrors the EventsLog
  // pattern in `packages/kaos-ui-react/src/debug/EventsLog.tsx`). Keeps
  // long streaming answers in view without yanking the user back when
  // they've scrolled up to read earlier turns.
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const transcriptSignal = useMemo(
    () =>
      stream.state.messages.reduce(
        (acc, m) => acc + (typeof m.content === "string" ? m.content.length : 0),
        0,
      ),
    [stream.state.messages],
  );
  // biome-ignore lint/correctness/useExhaustiveDependencies: transcriptSignal is the autoscroll trigger; we don't read it inside.
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [transcriptSignal]);

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

          <ExportMenu
            open={exportOpen}
            onOpenChange={setExportOpen}
            disabled={!meta || stream.state.messages.length === 0}
            onDownloadMarkdown={() => {
              if (meta) downloadMarkdown({ meta, messages: stream.state.messages });
            }}
            onDownloadJSON={() => {
              if (meta) downloadJSON({ meta, messages: stream.state.messages });
            }}
          />

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
            aria-label={citations.total > 0 ? `Citations (${citations.total})` : "Citations"}
            aria-pressed={citationsOpen}
          >
            <Quote className="h-3.5 w-3.5" />
            {citations.total > 0 && (
              <span className="tabular-nums text-[10px]">{citations.total}</span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setVfsOpen((v) => !v)}
            disabled={!meta}
            className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40 ${
              vfsOpen ? "bg-muted text-foreground" : ""
            }`}
            title={
              vfs.data
                ? `${vfs.data.nodes.length} VFS entries`
                : "Session VFS explorer (operator view)"
            }
            aria-label={
              vfs.data
                ? `Session VFS explorer (${vfs.data.nodes.length} entries)`
                : "Session VFS explorer"
            }
            aria-pressed={vfsOpen}
          >
            <FolderTree className="h-3.5 w-3.5" />
            {vfs.data && vfs.data.nodes.length > 0 && (
              <span className="tabular-nums text-[10px]">{vfs.data.nodes.length}</span>
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
            onClick={() => setTranscriptWide((v) => !v)}
            disabled={!meta}
            className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40 ${
              transcriptWide ? "bg-muted text-foreground" : ""
            }`}
            title={
              transcriptWide
                ? "Transcript width: wide — switch to narrow (72ch measure)"
                : "Transcript width: narrow — switch to wide (scales with viewport)"
            }
            aria-label="Toggle transcript width"
            aria-pressed={transcriptWide}
          >
            {transcriptWide ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
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

        <div ref={transcriptRef} className="flex-1 overflow-y-auto">
          <div
            className={`mx-auto px-6 py-8 ${transcriptWide ? "max-w-[min(96ch,90vw)]" : "max-w-3xl"}`}
            role="log"
            aria-live="polite"
          >
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
                  onFeedback={onFeedback}
                  onRegenerate={onRegenerate}
                  onEditPrior={onEditPrior}
                />
              ))}
            </div>

            <TurnStatus status={stream.state.status} />
          </div>
        </div>

        <DropZone onDrop={onAttach} disabled={!meta} />

        {uploadError && (
          <div
            className={`mx-auto px-4 ${transcriptWide ? "max-w-[min(96ch,90vw)]" : "max-w-3xl"}`}
          >
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
          <div
            className={`mx-auto px-4 ${transcriptWide ? "max-w-[min(96ch,90vw)]" : "max-w-3xl"}`}
          >
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

        <div className="relative">
          <Composer
            value={input}
            onChange={setInput}
            onSubmit={onSubmit}
            onStop={stream.abort}
            pending={stream.state.pending}
            placeholder={`Message ${meta?.title ?? "this conversation"}…  ·  type / for skills`}
            onAttach={onAttach}
            uploading={upload.isPending}
            leftChips={
              meta && (
                <>
                  <ModelPickerChip
                    value={meta.model}
                    onChange={onModelChange}
                    disabled={stream.state.pending}
                  />
                  <PlanActChip meta={meta} disabled={stream.state.pending} />
                </>
              )
            }
          />
          {/*
            Slash menu floats above the textarea anchored to the
            composer container. The composer itself doesn't know
            about skills — keeping the menu out of the package lets
            us swap server-loaded skill registries in later without
            changing the component API.
          */}
          <div
            className={`mx-auto px-4 pointer-events-none ${transcriptWide ? "max-w-[min(96ch,90vw)]" : "max-w-3xl"}`}
          >
            <div className="relative pointer-events-auto">
              <SlashMenu
                skills={BUILTIN_SKILLS}
                query={slashQuery}
                open={slashOpen}
                onPick={onPickSkill}
                // Esc dismisses the menu without destroying the
                // user's draft — strip the leading `/<query>` token
                // and keep whatever follows. Previously this was
                // `setInput("")` which wiped real text the user had
                // pasted starting with a slash.
                onClose={() => {
                  setInput((cur) => {
                    if (!cur.startsWith("/")) return cur;
                    const rest = cur.replace(/^\/\S*\s*/, "");
                    return rest;
                  });
                }}
              />
            </div>
          </div>
        </div>

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
        onRemove={(filename) => removeFile.mutate(filename)}
        removing={
          removeFile.variables && removeFile.isPending ? new Set([removeFile.variables]) : undefined
        }
        onAskAboutSelection={onAskAboutSelection}
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

      <VfsExplorer
        open={vfsOpen}
        onClose={() => setVfsOpen(false)}
        nodes={vfs.data?.nodes ?? []}
        loading={vfs.isLoading}
        errorCount={vfs.data?.error_count ?? 0}
        showSidecars={vfsShowSidecars}
        onShowSidecarsChange={setVfsShowSidecars}
        onRefresh={() => vfs.refetch()}
        refreshing={vfs.isFetching && !vfs.isLoading}
      />
    </div>
  );
}

/**
 * Chat-header Export menu. Keyboard-accessible dropdown with two
 * actions (Markdown / JSON). Mirrors the dismiss pattern from
 * PlanActChip — Escape + click-outside close the menu, focus
 * returns to the trigger after pick. Proper menu / menuitem ARIA
 * roles so screen-reader users see this as a real menu.
 */
function ExportMenu(props: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  disabled: boolean;
  onDownloadMarkdown: () => void;
  onDownloadJSON: () => void;
}) {
  const { open, onOpenChange, disabled, onDownloadMarkdown, onDownloadJSON } = props;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) onOpenChange(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onOpenChange]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => onOpenChange(!open)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md hover:bg-muted disabled:opacity-40"
        title="Export transcript"
      >
        <Download className="h-3.5 w-3.5" />
        Export
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Export transcript"
          className="absolute right-0 top-9 z-10 bg-card border border-border rounded-md min-w-[180px] py-1 text-sm shadow-md"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              onDownloadMarkdown();
              onOpenChange(false);
            }}
            className="w-full text-left px-3 py-1.5 hover:bg-muted focus:bg-muted focus:outline-none"
          >
            Download Markdown
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              onDownloadJSON();
              onOpenChange(false);
            }}
            className="w-full text-left px-3 py-1.5 hover:bg-muted focus:bg-muted focus:outline-none"
          >
            Download JSON
          </button>
        </div>
      )}
    </div>
  );
}
