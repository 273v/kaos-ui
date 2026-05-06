/**
 * Message — chat message renderer. No bubbles.
 *
 * - User: muted prose, indented with a 2 px stone-300 left border.
 *   Matches the Harvey/Legora/Midpage editorial pattern (you read
 *   what you wrote in a quieter type, then the assistant answers in
 *   primary type).
 * - Assistant: full-width prose in the primary text color. Streamed
 *   tokens land here as they arrive (parent passes `text` updated
 *   on every SSE delta). When markdown rendering ships in Phase B,
 *   the `<div>` wrapping `text` becomes a `<MarkdownMessage>`.
 * - Error: red surface, `recovery_hint` prominent.
 */
import { cn } from "@{{KAOS_NPM_SLUG}}/ui/lib/utils";

export type MessageRole = "user" | "agent" | "error";

interface MessageProps {
  role: MessageRole;
  text: string;
  /** When true, render a 1px caret at the tail of an assistant
   *  message to signal "still streaming". */
  streaming?: boolean;
}

export function Message({ role, text, streaming }: MessageProps) {
  if (role === "error") {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        {text}
      </div>
    );
  }

  if (role === "user") {
    return (
      <div className="border-l-2 border-stone-300 pl-4 text-sm leading-relaxed text-muted-foreground">
        {text}
      </div>
    );
  }

  // Assistant
  return (
    <div className="text-sm leading-relaxed text-foreground">
      {/* Once streamdown lands in Phase B this renders Markdown.
       *  For Phase A we render plain prose with whitespace-pre-wrap so
       *  newlines from the model are visible. */}
      <div className="whitespace-pre-wrap">
        {text}
        {streaming ? (
          <span
            className={cn(
              "ml-0.5 inline-block h-[1em] w-[2px] -translate-y-[2px] animate-pulse bg-foreground/60 align-middle",
            )}
            aria-hidden="true"
          />
        ) : null}
      </div>
    </div>
  );
}
