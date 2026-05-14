import { useMemo } from "react";

import type { ChatMessage } from "@/lib/chat-state";
import { renderMarkdown } from "@/lib/markdown";
import { ToolCallBlock } from "./ToolCallBlock";
import { UsageChip } from "./UsageChip";

interface Props {
  message: ChatMessage;
}

/**
 * One message in the transcript. Flat role-labeled block (no bubbles)
 * per UX-LANGUAGE.md § 4.2.
 *
 * LOW #3 — assistant messages render as Markdown (links + lists +
 * bold + code blocks). User / tool / error messages stay
 * `whitespace-pre-wrap` plain text so the user sees exactly what they
 * typed and so tool stack traces don't get parsed weirdly.
 */
export function Message({ message }: Props) {
  const isUser = message.role === "user";
  const isError = message.role === "error";
  const isTool = message.role === "tool";
  const isAssistant = message.role === "assistant";

  const roleLabel = isUser ? "You" : isError ? "Error" : isTool ? "Tool" : "Assistant";

  // Sanitized markdown HTML for assistant messages; everything else is plain.
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
          className={
            "text-[11px] uppercase tracking-wide " +
            (isError ? "text-destructive" : "text-muted-foreground font-serif")
          }
        >
          {roleLabel}
        </span>
      </header>

      <div
        className={
          "prose prose-sm max-w-none leading-relaxed " +
          (isAssistant ? "" : "whitespace-pre-wrap ") +
          (isError ? "text-destructive" : "text-foreground")
        }
      >
        {isAssistant && rendered ? (
          // markdown.ts sanitizes raw HTML, validates link schemes,
          // and pins external links to target=_blank rel=noopener.
          // biome-ignore lint/security/noDangerouslySetInnerHtml: rendered output is sanitized in lib/markdown.ts (html:false, validateLink whitelist).
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

      {(message.tokens || message.cost_usd) && !message.streaming && (
        <UsageChip tokens={message.tokens} costUsd={message.cost_usd} />
      )}
    </article>
  );
}
