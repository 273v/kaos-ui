/**
 * One message in the transcript. Flat role-labeled block (no bubbles).
 *
 * Assistant messages render as Markdown via `renderMarkdown` (links +
 * lists + bold + code blocks + tables). User / tool / error messages
 * stay `whitespace-pre-wrap` plain text so the user sees exactly what
 * they typed and so tool stack traces don't get parsed weirdly.
 *
 * `tool_calls` render as inline `<ToolCallBlock>` cards below the
 * message text. Usage chip appears under finalized assistant messages
 * once `tokens` / `cost_usd` are populated.
 */

import { Loader2 } from "lucide-react";
import { useMemo } from "react";

import type { ChatMessage } from "../lib/chat-state.js";
import { renderMarkdown } from "../lib/markdown.js";
import { CapabilityApproval, type CapabilityDecision } from "./CapabilityApproval.js";
import { ElevationPill } from "./ElevationPill.js";
import { GoalCheckBadge } from "./GoalCheckBadge.js";
import { LoopTerminatedBanner } from "./LoopTerminatedBanner.js";
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
  onCapabilityDecide?(
    decision: CapabilityDecision,
    groups: string[],
    messageId: string,
  ): void;
}

export function Message({
  message,
  verboseTools = false,
  onPinElevationToSession,
  onCapabilityDecide,
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

  // Subtle role-differentiated chrome (kaos-ui 0.1.0a8). Iterated
  // after a "too close / unpolished" pass:
  //   - User turns: tint-only soft inset (`bg-muted/45`), generous
  //     rounded corners, edge-padded to the transcript column.
  //     No border, no shadow — just a faint warm panel.
  //   - Assistant turns: completely flat. No rail, no card. The
  //     agent IS the page speaking; visual hierarchy comes from
  //     the bg-tinted user card preceding it.
  //   - Tool / error turns keep their destructive accent.
  //
  // Reduces the two-rail clutter the previous version had — the
  // user card and assistant left-rail were drawing competing
  // vertical lines a few pixels apart, which read as noise.
  const articleClass = isError
    ? "py-6 border-l-2 border-destructive pl-4"
    : isUser
      ? "my-4 rounded-xl bg-muted/45 px-5 py-4"
      : "py-6";

  return (
    <article
      className={articleClass}
      aria-label={`${roleLabel} message`}
    >
      <header className="mb-2">
        <span
          className={
            "text-[11px] uppercase tracking-[0.08em] font-medium " +
            (isError
              ? "text-destructive"
              : isUser
                ? "text-foreground/55"
                : "text-foreground/70")
          }
        >
          {roleLabel}
        </span>
      </header>

      {isAssistant && message.tool_policy && (
        <ToolPolicyBadge policy={message.tool_policy} />
      )}

      {isAssistant && message.elevations && message.elevations.length > 0 && (
        <ElevationPill
          elevations={message.elevations}
          onPinToSession={onPinElevationToSession}
        />
      )}

      {/* Reasoning summary — rendered ABOVE the answer body so the
          reader sees the critic's verdict before scrolling through
          the full prose. Collapsed by default; click to expand. */}
      {isAssistant && message.goal_check && (
        <ReasoningSummary goal={message.goal_check} />
      )}

      <div
        className={
          // Assistant turns flow as rendered markdown via `.kaos-md`
          // which carries the editorial body type (16px / 1.65).
          // User + tool + error turns are pre-wrapped plain text and
          // use the chrome-body size (15px) so the user's question
          // doesn't look like a heading next to the answer.
          (isAssistant ? "kaos-md max-w-none " : "text-[15px] leading-relaxed whitespace-pre-wrap ") +
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
          // below this body update live as each call returns.
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

      {message.tool_calls && message.tool_calls.length > 0 && (
        <div className="mt-3 space-y-2">
          {message.tool_calls.map((tc) => (
            <ToolCallBlock
              key={tc.id}
              call={tc}
              defaultOpen={
                verboseTools ||
                message.streaming ||
                tc.status === "error" ||
                tc.status === "running"
              }
            />
          ))}
        </div>
      )}

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

      {isAssistant && message.goal_check && (
        <GoalCheckBadge goal={message.goal_check} />
      )}

      {isAssistant && message.loop_termination && (
        <LoopTerminatedBanner termination={message.loop_termination} />
      )}

      {isAssistant && !message.streaming && (
        <UsageChip
          latencyMs={message.latency_ms}
          tokens={message.tokens}
          costUsd={message.cost_usd}
          toolCount={message.tool_calls?.length}
        />
      )}
    </article>
  );
}
