/**
 * One message in the transcript. Flat role-labeled block (no bubbles).
 *
 * Assistant messages render as Markdown via `renderMarkdown` (links +
 * lists + bold + code blocks + tables). User / tool / error messages
 * stay `whitespace-pre-wrap` plain text so the user sees exactly what
 * they typed and so tool stack traces don't get parsed weirdly.
 *
 * Intra-turn order (2026-05-19 chronological redesign): the assistant
 * block renders `[plan card] → [tool calls in start order] → [prose
 * answer]`. Tool calls precede the prose because the agent ran them
 * BEFORE writing the answer — the reader sees the inputs to the
 * synthesis before the synthesis itself. `tool_calls[]` is already
 * in `Span(tool_call, start)` order (see appendToolCall in
 * event-handler.ts), so the array iteration IS wall-clock order.
 *
 * The role header is `position: sticky; top: 0` inside the transcript
 * scroll container, so when the user is reading a long answer the
 * "ASSISTANT" chip stays pinned to the viewport top — the
 * Slack-thread / Notion-page pattern. Usage chip appears under
 * finalized assistant messages once `tokens` / `cost_usd` are
 * populated.
 */

import {
  Check,
  ChevronRight,
  Copy,
  Loader2,
  Pencil,
  RotateCw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useMemo, useState } from "react";

import type { ChatMessage } from "../lib/chat-state.js";
import { copyToClipboard } from "../lib/copy-to-clipboard.js";
import { renderMarkdown } from "../lib/markdown.js";
import { CapabilityApproval, type CapabilityDecision } from "./CapabilityApproval.js";
import { ElevationPill } from "./ElevationPill.js";
import { GoalCheckBadge } from "./GoalCheckBadge.js";
import { LoopTerminatedBanner } from "./LoopTerminatedBanner.js";
import { PlanCard } from "./PlanCard.js";
import { ReasoningSummary } from "./ReasoningSummary.js";
import { ToolCallBlock } from "./ToolCallBlock.js";
import { ToolPolicyBadge } from "./ToolPolicyBadge.js";
import { UsageChip } from "./UsageChip.js";

interface Props {
  message: ChatMessage;
  /**
   * When true, every tool-call card under this message starts
   * expanded. Defaults to true while the message is still streaming
   * (so the user sees tool activity live) AND when any tool call on
   * this message has errored. The host can also force this via the
   * `verboseTools` prop — typically wired to a header toggle.
   */
  verboseTools?: boolean;
  /**
   * Wired to the host's "Pin to session" handler — typically a
   * PATCH /v1/chat/sessions/{id}/tool-set that adds the elevated
   * groups to the session's persistent ceiling. When omitted, the
   * elevation pill is read-only.
   */
  onPinElevationToSession?(groups: string[]): void;
  /**
   * Wired to the host's resume handler for yellow-confirm capability
   * pauses. Called with the user's decision, the groups the loop
   * requested, and the id of the message that carries the
   * capability_request snapshot (so the host can clear it via
   * `useSendMessage().clearCapability(messageId)`). When omitted,
   * the approval card renders disabled.
   */
  onCapabilityDecide?(decision: CapabilityDecision, groups: string[], messageId: string): void;
  /**
   * Plan Issue 10 layer 2 — host receives thumbs-up / thumbs-down
   * feedback per assistant message and posts to the SPA backend's
   * ``POST /v1/chat/sessions/{sid}/messages/{messageId}/feedback``
   * endpoint. When omitted, the buttons stay hidden — the affordance
   * is opt-in so embedders without a feedback persistence layer
   * don't get a non-functional button.
   */
  onFeedback?(messageId: string, value: "up" | "down"): void;
  /**
   * Plan Issue 10 layer 3 — regenerate this assistant turn from
   * the prior user message. Host posts to
   * ``POST /v1/chat/sessions/{sid}/messages/{messageId}/regenerate``
   * which rewinds the persisted MESSAGES section to BEFORE the
   * targeted assistant turn and re-dispatches the prior user
   * message through the same chat flow (lock-aware per #588).
   * The new turn streams in over SSE just like a fresh send.
   *
   * Host receives the assistant message id. When omitted, the
   * button stays hidden — opt-in so embedders that don't expose
   * the regenerate endpoint don't get a non-functional button.
   */
  onRegenerate?(messageId: string): void;
  /**
   * Plan Issue 10 layer 4 — edit a prior user message in place.
   * Host posts to
   * ``PATCH /v1/chat/sessions/{sid}/messages/{idx}`` with the edited
   * text; the backend replaces the user message content and
   * truncates every subsequent item, then the SPA reissues the
   * edited user message to trigger a fresh run.
   *
   * Host receives the user message id; the SPA host resolves the
   * persisted index from the visible transcript before posting.
   * When omitted, the affordance stays hidden — opt-in so embedders
   * that don't expose the edit endpoint don't surface a
   * non-functional pencil.
   *
   * The component itself owns the inline edit state machine
   * (idle → editing → saving → settled); the host receives the
   * final value via the callback.
   */
  onEditPrior?(messageId: string, newText: string): void;
}

/**
 * Tiny copy-to-clipboard button shown next to the UsageChip on every
 * finalized assistant message. Consumer-AI table-stakes parity
 * (Pattern α from the consumer-AI parity audit): ChatGPT / Claude.ai
 * both expose copy on every assistant turn. Copies the rendered
 * Markdown source (`message.content`) — agents that emit code blocks
 * and tables keep them intact when pasted into other tools.
 *
 * Mirrors the `ToolCallBlock` CopyJsonButton state machine
 * (idle/copied/failed) and the `lib/copy-to-clipboard` helper that
 * falls back to `document.execCommand("copy")` when
 * `navigator.clipboard` is unavailable (insecure context, sandboxed
 * iframe, headless-Chrome unfocused-page rejection).
 */
function CopyMessageButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const onClick = async () => {
    const ok = await copyToClipboard(text);
    setState(ok ? "copied" : "failed");
    setTimeout(() => setState("idle"), 1500);
  };
  const label =
    state === "copied"
      ? "Copied"
      : state === "failed"
        ? "Copy failed — your browser blocked clipboard write"
        : "Copy answer";
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 " +
        "text-xs text-muted-foreground hover:text-foreground " +
        "hover:bg-muted/60 transition-colors"
      }
    >
      {state === "copied" ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      <span className="hidden sm:inline">{state === "copied" ? "Copied" : "Copy"}</span>
    </button>
  );
}

/**
 * Plan Issue 10 layer 2 — thumbs-up / thumbs-down per assistant
 * message. Persists to the SPA backend's append-only JSONL audit
 * log via the host-provided ``onFeedback`` callback (see
 * ``app/routers/feedback.py``).
 *
 * Submission is fire-and-forget at this layer; we record the
 * sentiment locally for visual confirmation. If the user changes
 * their mind they can click the other thumb — the backend keeps
 * every submission in the timeline (no DELETE / PATCH on feedback).
 */
function FeedbackButtons({
  messageId,
  onFeedback,
}: {
  messageId: string;
  onFeedback: (id: string, value: "up" | "down") => void;
}) {
  const [submitted, setSubmitted] = useState<"up" | "down" | null>(null);
  const click = (value: "up" | "down") => {
    onFeedback(messageId, value);
    setSubmitted(value);
  };
  const baseClass =
    "inline-flex items-center justify-center rounded p-1 " +
    "text-muted-foreground hover:text-foreground " +
    "hover:bg-muted/60 transition-colors";
  return (
    <span className="inline-flex items-center gap-0.5">
      <button
        type="button"
        onClick={() => click("up")}
        title={submitted === "up" ? "Thanks — recorded" : "Helpful"}
        aria-label="Mark answer helpful"
        aria-pressed={submitted === "up"}
        className={submitted === "up" ? `${baseClass} text-foreground bg-muted/60` : baseClass}
      >
        <ThumbsUp className="h-3 w-3" />
      </button>
      <button
        type="button"
        onClick={() => click("down")}
        title={submitted === "down" ? "Thanks — recorded" : "Not helpful"}
        aria-label="Mark answer not helpful"
        aria-pressed={submitted === "down"}
        className={submitted === "down" ? `${baseClass} text-foreground bg-muted/60` : baseClass}
      >
        <ThumbsDown className="h-3 w-3" />
      </button>
    </span>
  );
}

/**
 * Plan Issue 10 layer 3 — "regenerate this assistant turn from the
 * prior user message". Mirrors the FeedbackButtons state machine
 * (idle → in-flight → settled). The host's onRegenerate callback
 * is responsible for the actual POST + the SSE resubscribe; this
 * component just gives a visible spinner while the round-trip is
 * in flight so the user can't double-click.
 */
function RegenerateButton({
  messageId,
  onRegenerate,
}: {
  messageId: string;
  onRegenerate: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const click = () => {
    if (busy) return;
    setBusy(true);
    try {
      onRegenerate(messageId);
    } finally {
      // The host typically navigates / re-subscribes to SSE, so we
      // give a short visual lock then return to idle. If the host
      // re-renders the transcript (replacing this message), the
      // component unmounts anyway and the timeout is harmless.
      setTimeout(() => setBusy(false), 1500);
    }
  };
  const label = busy ? "Regenerating…" : "Regenerate";
  return (
    <button
      type="button"
      onClick={click}
      disabled={busy}
      title={label}
      aria-label={label}
      aria-busy={busy}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors ${
        busy ? "opacity-60 cursor-wait" : ""
      }`}
    >
      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCw className="h-3 w-3" />}
      <span>{busy ? "Regenerating…" : "Regenerate"}</span>
    </button>
  );
}

/**
 * Plan Issue 10 layer 4 — "edit this user message in place".
 * Surfaces a small pencil button on USER turns. Clicking it
 * swaps the message content for a textarea + Save/Cancel pair;
 * Save fires onEditPrior(id, newText) and the host POSTs to
 * PATCH /messages/{idx}. Cancel reverts without calling the host.
 */
function EditPriorButton({
  messageId,
  initialText,
  onEditPrior,
}: {
  messageId: string;
  initialText: string;
  onEditPrior: (id: string, newText: string) => void;
}) {
  const [mode, setMode] = useState<"idle" | "editing" | "saving">("idle");
  const [draft, setDraft] = useState(initialText);

  if (mode === "idle") {
    return (
      <button
        type="button"
        onClick={() => {
          setDraft(initialText);
          setMode("editing");
        }}
        title="Edit and resend"
        aria-label="Edit this message and resend"
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
      >
        <Pencil className="h-3 w-3" />
        <span>Edit</span>
      </button>
    );
  }

  const save = () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === initialText.trim()) {
      setMode("idle");
      return;
    }
    setMode("saving");
    try {
      onEditPrior(messageId, trimmed);
    } finally {
      // Host typically refreshes the transcript on the next SSE
      // event; visual lock against double-fire matches the
      // RegenerateButton's 1.5s pattern.
      setTimeout(() => setMode("idle"), 1500);
    }
  };

  return (
    <div className="mt-2 flex flex-col gap-2">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        disabled={mode === "saving"}
        rows={Math.min(8, Math.max(2, draft.split("\n").length))}
        className="w-full resize-y rounded border border-border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
        aria-label="Edit message"
      />
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => setMode("idle")}
          disabled={mode === "saving"}
          className="rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={mode === "saving" || !draft.trim()}
          className={`inline-flex items-center gap-1 rounded bg-foreground px-2 py-0.5 text-xs text-background hover:bg-foreground/90 transition-colors ${
            mode === "saving" || !draft.trim() ? "opacity-60 cursor-wait" : ""
          }`}
          aria-busy={mode === "saving"}
        >
          {mode === "saving" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          <span>{mode === "saving" ? "Saving…" : "Save & resend"}</span>
        </button>
      </div>
    </div>
  );
}

export function Message({
  message,
  verboseTools = false,
  onPinElevationToSession,
  onCapabilityDecide,
  onFeedback,
  onRegenerate,
  onEditPrior,
}: Props) {
  const isUser = message.role === "user";
  const isError = message.role === "error";
  const isTool = message.role === "tool";
  const isAssistant = message.role === "assistant";

  const roleLabel = isUser ? "You" : isError ? "Error" : isTool ? "Tool" : "Assistant";

  const rendered = useMemo(() => {
    if (isAssistant && message.content) return renderMarkdown(message.content);
    return null;
  }, [isAssistant, message.content]);

  // Asymmetric role chrome (kaos-ui 0.1.0a10). The metaphor:
  //   - USER turns = an editor's note pinned to the page. Crisp
  //     warm-tinted card, hairline border, subtle inset shadow.
  //     Reads as "this is the instruction the agent is working
  //     against." 6px radius (rounded-md), not 12px — legal-doc
  //     feel, not chat-bubble.
  //   - ASSISTANT turns = the page speaking. No card, no border.
  //     Stays flat so the editorial markdown (headings, tables,
  //     justified prose) IS the visual surface. The leading
  //     accent dot on the role label is the only signal — a tiny
  //     amber/stone bullet, like a sidenote marker.
  //   - TOOL / ERROR turns keep their destructive accent rail.
  //
  // The asymmetry creates the alternation rhythm: card (user) →
  // page (assistant) → card (user) → page (assistant). User cards
  // mark the boundaries between turns; assistant prose fills the
  // page in between. No two cards in a row, no chat-bubble noise.
  // #314 AgenticLoop UX polish: assistant turns use ``space-y-3`` so
  // the per-message components (ToolPolicyBadge, ElevationPill,
  // ReasoningSummary, PlanCard, ToolCallTimeline, prose body,
  // CapabilityApproval, GoalCheckBadge, LoopTerminatedBanner,
  // UsageChip) get consistent vertical breathing room instead of
  // each component managing its own ad-hoc ``mb-3``. The header has
  // ``mb-2`` baked in and uses ``sticky top-0``, so the first child
  // gap-after-header still reads correctly.
  const articleClass = isError
    ? "py-6 border-l-2 border-destructive pl-4 space-y-3"
    : isUser
      ? "my-6 rounded-md border border-[oklch(0.88_0.005_80)] " +
        "bg-[oklch(0.945_0.005_85)] px-5 py-[1.125rem] " +
        "shadow-[0_1px_2px_oklch(0_0_0_/_0.05)] space-y-3"
      : "py-6 space-y-3";

  return (
    <article className={articleClass} aria-label={`${roleLabel} message`}>
      <header
        // Sticky role header — pins the role chip + dot to the top
        // of the scroll viewport while a long message is being read.
        //
        // Background treatment is conditional:
        //   - USER turns already sit in a tinted card; the header
        //     inherits the card's bg (transparent). A paper-colored
        //     backdrop would read as a white stripe inside a tinted
        //     card.
        //   - ASSISTANT (and tool/error) turns flow on the paper bg,
        //     so the chip needs its own paper-colored backdrop +
        //     blur to stay readable when prose scrolls behind it.
        //
        // `top: 0` is relative to the transcript scroll container.
        // `-mx-1 px-1` extends the blur past the article's text
        // column so it visually covers the gutter too.
        className={`mb-2 flex items-center gap-1.5 sticky top-0 z-10 -mx-1 px-1 py-1 ${isUser ? "" : "bg-[oklch(0.984_0.003_85_/_0.85)] backdrop-blur-sm"}`}
      >
        {/* Role marker dot — colored bullet preceding the role label.
         * Amber (accent) for assistant signals "the AI's voice"; stone
         * for user signals "the human's instruction"; destructive red
         * for errors. The dot does the visual work without requiring
         * a card around the assistant prose. */}
        <span
          aria-hidden
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            isError
              ? "bg-destructive"
              : isUser
                ? "bg-foreground/30"
                : isTool
                  ? "bg-foreground/40"
                  : "bg-accent"
          }`}
        />
        <span
          className={`text-[11px] uppercase tracking-[0.08em] font-medium ${isError ? "text-destructive" : isUser ? "text-foreground/55" : "text-foreground/70"}`}
        >
          {roleLabel}
        </span>
      </header>

      {isAssistant && message.tool_policy && <ToolPolicyBadge policy={message.tool_policy} />}

      {isAssistant && message.elevations && message.elevations.length > 0 && (
        <ElevationPill elevations={message.elevations} onPinToSession={onPinElevationToSession} />
      )}

      {/* Reasoning summary — rendered ABOVE the answer body so the
          reader sees the critic's verdict before scrolling through
          the full prose. Collapsed by default; click to expand. */}
      {isAssistant && message.goal_check && <ReasoningSummary goal={message.goal_check} />}

      {/*
        Chronological intra-turn order (2026-05-19 redesign):
          1. Plan (if any) — the agent's intent for the turn.
          2. Tool calls in start-order — the actual work.
          3. Prose answer — the synthesis.
        Tool cards precede the prose because that matches the order
        events happened in. Reading the answer first and then the
        tool list (the legacy order) hides the activity that
        produced the answer.
      */}
      {isAssistant && message.plan && message.plan.steps.length > 0 && (
        // #314 polish: removed inline mb-3 wrapper — the article-level
        // space-y-3 handles vertical rhythm between AgenticLoop
        // sections consistently now.
        <PlanCard
          plan={message.plan}
          defaultOpen={
            verboseTools ||
            message.streaming ||
            message.plan.steps.some((s) => s.status === "error" || s.status === "running")
          }
        />
      )}

      {isAssistant && message.tool_calls && message.tool_calls.length > 0 && (
        <ToolCallTimeline calls={message.tool_calls} verboseTools={verboseTools} />
      )}

      <div
        className={
          // Assistant turns flow as rendered markdown via `.kaos-md`
          // which carries the editorial body type (16px / 1.65).
          // User + tool + error turns are pre-wrapped plain text and
          // use the chrome-body size (15px) so the user's question
          // doesn't look like a heading next to the answer.
          (isAssistant
            ? "kaos-md max-w-none "
            : "text-[15px] leading-relaxed whitespace-pre-wrap ") +
          (isError ? "text-destructive" : "text-foreground")
        }
      >
        {isAssistant && rendered ? (
          // renderMarkdown disables raw HTML and validates link schemes
          // (http / https / mailto only); external links are pinned to
          // target=_blank rel=noopener.
          // biome-ignore lint/security/noDangerouslySetInnerHtml: rendered HTML is sanitized in lib/markdown.ts (html:false + validateLink whitelist).
          <div dangerouslySetInnerHTML={{ __html: rendered }} />
        ) : isAssistant && message.streaming && !message.content ? (
          // Mid-turn with no prose yet — the agent is either thinking
          // or running tool calls. Without this placeholder the user
          // sees a bare role label + a tiny cursor block and can't
          // tell anything's happening. Prominent spinner + label
          // tells them the turn is in flight; the tool-call cards
          // above this body update live as each call returns.
          <div className="flex items-center gap-2 text-sm text-foreground/60 italic">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {message.tool_calls && message.tool_calls.length > 0
              ? `Calling ${message.tool_calls.length} tool${message.tool_calls.length === 1 ? "" : "s"}…`
              : "Working…"}
          </div>
        ) : (
          message.content || (message.streaming ? "" : <em className="opacity-60">(empty)</em>)
        )}
        {message.streaming && message.content && (
          <span
            aria-hidden
            className="ml-0.5 inline-block w-[1ch] -mb-0.5 animate-pulse text-accent"
          >
            ▍
          </span>
        )}
      </div>

      {isAssistant && message.capability_request && (
        <CapabilityApproval
          request={message.capability_request}
          onDecide={
            onCapabilityDecide
              ? (decision, groups) => onCapabilityDecide(decision, groups, message.id)
              : undefined
          }
        />
      )}

      {isAssistant && message.goal_check && <GoalCheckBadge goal={message.goal_check} />}

      {isAssistant && message.loop_termination && (
        <LoopTerminatedBanner termination={message.loop_termination} />
      )}

      {isAssistant && !message.streaming && (
        <div className="flex items-center gap-2 flex-wrap">
          <UsageChip
            latencyMs={message.latency_ms}
            tokens={message.tokens}
            costUsd={message.cost_usd}
            toolCount={message.tool_calls?.length}
          />
          {message.content ? <CopyMessageButton text={message.content} /> : null}
          {onRegenerate ? (
            <RegenerateButton messageId={message.id} onRegenerate={onRegenerate} />
          ) : null}
          {onFeedback ? <FeedbackButtons messageId={message.id} onFeedback={onFeedback} /> : null}
        </div>
      )}

      {/*
       * Plan Issue 10 layer 4 — edit-prior affordance on user turns.
       * Hidden when the host doesn't supply onEditPrior (opt-in).
       * The EditPriorButton itself owns the inline edit state
       * machine; on Save it fires onEditPrior(id, newText) and the
       * host POSTs PATCH /messages/{idx} which truncates forward.
       */}
      {isUser && onEditPrior && message.content ? (
        <EditPriorButton
          messageId={message.id}
          initialText={message.content}
          onEditPrior={onEditPrior}
        />
      ) : null}
    </article>
  );
}

/**
 * Tool-call timeline block.
 *
 * Two states:
 *   - **expanded**: full ordinal-numbered card list with per-call
 *     `<ToolCallBlock>`. Default when ANY call is running OR errored
 *     (the user wants to see live activity and triage failures), OR
 *     when `verboseTools` is on, OR when count ≤ 1.
 *   - **collapsed**: a compact summary chip "ACTIVITY · 3 CALLS ·
 *     tool-a, tool-b, tool-c ▸". Default once all calls have
 *     completed successfully. Click the chip to expand.
 *
 * The per-card `defaultOpen` no longer fires on `message.streaming` —
 * each card decides its own state based on its OWN status. A
 * completed call collapses immediately even if the assistant prose
 * is still streaming below.
 */
function ToolCallTimeline({
  calls,
  verboseTools,
}: {
  calls: NonNullable<ChatMessage["tool_calls"]>;
  verboseTools: boolean;
}) {
  const anyRunning = calls.some((tc) => tc.status === "running");
  const anyErrored = calls.some((tc) => tc.status === "error");
  // Default-expanded state: user hasn't toggled, so we follow the
  // "show live activity, hide completed history" rule. Once the
  // user clicks the chip to expand, we honor that for the rest of
  // the session. (Re-collapsing requires reload — that's deliberate;
  // a per-message persistence layer would be heavier than the value.)
  const groupable = calls.length > 1 && !verboseTools && !anyRunning && !anyErrored;
  const [userExpanded, setUserExpanded] = useState(false);
  const showExpanded = !groupable || userExpanded;
  // #507: group-level expand-all / collapse-all. `null` means the
  // user hasn't clicked the master toggle yet — each card honors its
  // own per-card state. `true` / `false` propagates to every card via
  // the `forceOpen` prop.
  const [forceAllOpen, setForceAllOpen] = useState<boolean | null>(null);

  // Compact summary names — dedupe + cap at first 3 for the chip,
  // suffix with "+N more" when there are extras. Reads like the
  // section breadcrumb in a Notion doc.
  const summaryNames = useMemo(() => {
    const seen = new Set<string>();
    const names: string[] = [];
    for (const tc of calls) {
      const name = tc.name || "(unnamed)";
      if (seen.has(name)) continue;
      seen.add(name);
      names.push(name);
    }
    return names;
  }, [calls]);
  const visibleNames = summaryNames.slice(0, 3);
  const extraNames = summaryNames.length - visibleNames.length;

  if (!showExpanded) {
    return (
      <div className="mb-3">
        <button
          type="button"
          onClick={() => setUserExpanded(true)}
          className={
            "group flex w-full items-center gap-2 rounded-md " +
            "border border-border/55 bg-muted/40 px-3 py-2 text-left " +
            "hover:bg-muted/70 transition-colors"
          }
          aria-expanded={false}
          aria-label={`Expand ${calls.length} tool calls`}
        >
          <ChevronRight
            className="h-3.5 w-3.5 shrink-0 text-foreground/50 transition-transform group-hover:translate-x-0.5"
            aria-hidden
          />
          <span className="text-[10px] uppercase tracking-[0.08em] font-medium text-foreground/55 shrink-0">
            Activity
          </span>
          <span aria-hidden className="text-foreground/30">
            ·
          </span>
          <span className="text-[11px] tabular-nums text-foreground/65 shrink-0">
            {calls.length} calls
          </span>
          <span aria-hidden className="text-foreground/30">
            ·
          </span>
          <span className="text-[11px] font-mono text-foreground/55 truncate min-w-0">
            {visibleNames.join(", ")}
            {extraNames > 0 && <span className="text-foreground/40"> +{extraNames} more</span>}
          </span>
        </button>
      </div>
    );
  }

  return (
    <div className="mb-3 space-y-2">
      {/* Activity-strip rail — tiny chronological breadcrumb above
          the cards, so the user can scan the sequence in one line
          before reading each card. Numbers reflect start-order
          (the array's natural order). When expanded after a
          collapse, also offers a click target to re-collapse. */}
      <div className="flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-foreground/55">
        <span>Activity</span>
        <span aria-hidden className="text-foreground/30">
          ·
        </span>
        <span className="tabular-nums">
          {calls.length} {calls.length === 1 ? "call" : "calls"}
        </span>
        <span aria-hidden className="text-foreground/30">
          ·
        </span>
        <span className="font-mono text-foreground/40 normal-case tracking-normal">
          chronological
        </span>
        {userExpanded && (
          <>
            <span aria-hidden className="text-foreground/30">
              ·
            </span>
            <button
              type="button"
              onClick={() => setUserExpanded(false)}
              className="text-foreground/50 hover:text-foreground transition-colors normal-case tracking-normal"
              aria-label="Collapse tool call list"
            >
              collapse
            </button>
          </>
        )}
        {/* #507: per-card expand-all / collapse-all. Visible when the
            group is expanded AND has more than one call. Click sets
            `forceAllOpen` which each card mirrors via the `forceOpen`
            prop. */}
        {calls.length > 1 && (
          <>
            <span aria-hidden className="text-foreground/30">
              ·
            </span>
            <button
              type="button"
              onClick={() => setForceAllOpen((prev) => !prev)}
              className="text-foreground/50 hover:text-foreground transition-colors normal-case tracking-normal"
              aria-label={
                forceAllOpen === true ? "Collapse all tool cards" : "Expand all tool cards"
              }
              aria-pressed={forceAllOpen === true}
              title={
                forceAllOpen === true
                  ? "Collapse all (every card shows just the header)"
                  : "Expand all (every card shows the full args + result)"
              }
            >
              {forceAllOpen === true ? "collapse all" : "expand all"}
            </button>
          </>
        )}
      </div>
      {calls.map((tc, i) => (
        <div key={tc.id} className="flex items-stretch gap-2">
          {/* Per-call ordinal — anchors each card to its place
              in the timeline. Numbered 1-based so the user can
              reference "call 3" out loud. */}
          <div aria-hidden className="flex w-6 shrink-0 flex-col items-center pt-1">
            <span className="font-mono text-[10px] text-foreground/45 tabular-nums">
              {String(i + 1).padStart(2, "0")}
            </span>
            {i < calls.length - 1 && <span className="mt-1 flex-1 w-px bg-border" />}
          </div>
          <div className="flex-1 min-w-0">
            <ToolCallBlock
              call={tc}
              defaultOpen={verboseTools || tc.status === "error" || tc.status === "running"}
              forceOpen={forceAllOpen ?? undefined}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
