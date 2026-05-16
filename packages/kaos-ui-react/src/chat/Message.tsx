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

import { useMemo } from "react";

import type { ChatMessage } from "../lib/chat-state.js";
import { renderMarkdown } from "../lib/markdown.js";
import { CapabilityApproval, type CapabilityDecision } from "./CapabilityApproval.js";
import { ElevationPill } from "./ElevationPill.js";
import { GoalCheckBadge } from "./GoalCheckBadge.js";
import { LoopTerminatedBanner } from "./LoopTerminatedBanner.js";
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
   * pauses. Called with the user's decision + the groups the loop
   * requested. When omitted, the approval card renders disabled.
   */
  onCapabilityDecide?(decision: CapabilityDecision, groups: string[]): void;
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

  return (
    <article
      className={`py-4 ${isError ? "border-l-2 border-destructive pl-3" : ""}`}
      aria-label={`${roleLabel} message`}
    >
      <header className="mb-1">
        <span
          className={`text-[11px] uppercase tracking-wide ${isError ? "text-destructive" : "text-muted-foreground"}`}
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

      <div
        className={`kaos-md max-w-none leading-relaxed ${isAssistant ? "" : "whitespace-pre-wrap "}${isError ? "text-destructive" : "text-foreground"}`}
      >
        {isAssistant && rendered ? (
          // renderMarkdown disables raw HTML and validates link schemes
          // (http / https / mailto only); external links are pinned to
          // target=_blank rel=noopener.
          // biome-ignore lint/security/noDangerouslySetInnerHtml: rendered HTML is sanitized in lib/markdown.ts (html:false + validateLink whitelist).
          <div dangerouslySetInnerHTML={{ __html: rendered }} />
        ) : (
          message.content || (message.streaming ? "" : <em className="opacity-60">(empty)</em>)
        )}
        {message.streaming && (
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
          onDecide={onCapabilityDecide}
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
