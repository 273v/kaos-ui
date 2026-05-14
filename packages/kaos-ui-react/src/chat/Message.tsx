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
import { ToolCallBlock } from "./ToolCallBlock.js";
import { UsageChip } from "./UsageChip.js";

interface Props {
  message: ChatMessage;
}

export function Message({ message }: Props) {
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
            <ToolCallBlock key={tc.id} call={tc} />
          ))}
        </div>
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
