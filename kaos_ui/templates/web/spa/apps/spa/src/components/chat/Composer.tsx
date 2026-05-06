/**
 * Composer — the chat input. Modeled after Harvey's centered card
 * with quick-action pills above and a send icon button on the right.
 *
 * - Multi-line `<textarea>` (auto-resize) — `Enter` submits, `Shift+Enter`
 *   inserts a newline (chat convention).
 * - Top row: `Matter ▾` placeholder, `+ Add sources` placeholder.
 *   These wire to real workspace selection in Phase B.
 * - Right side: send icon button. Disabled when empty or when a
 *   stream is in flight.
 */

import { Button } from "@{{KAOS_NPM_SLUG}}/ui/components/ui/button";
import { Textarea } from "@{{KAOS_NPM_SLUG}}/ui/components/ui/textarea";
import { cn } from "@{{KAOS_NPM_SLUG}}/ui/lib/utils";
import { ArrowUp, Briefcase, Paperclip, Plus } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef } from "react";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** True while an SSE stream is in flight; disables the send button. */
  pending: boolean;
  /** Hint shown in the textarea placeholder. */
  placeholder?: string;
  /** Compact mode for the empty-state hero (no Matter/Sources pills). */
  compact?: boolean;
}

export function Composer({
  value,
  onChange,
  onSubmit,
  pending,
  placeholder = "Ask anything…",
  compact = false,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea up to 200 px tall. Below that it tracks
  // content; above, it scrolls. The dependency on `value` is real:
  // we must re-measure `scrollHeight` after React commits the new
  // value to the DOM. biome's static analysis can't see that.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run on every value change to re-measure scrollHeight
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits; Shift+Enter inserts a newline. Standard chat UX.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (value.trim() && !pending) onSubmit();
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (value.trim() && !pending) onSubmit();
  }

  const canSend = value.trim().length > 0 && !pending;

  return (
    <form
      onSubmit={handleSubmit}
      className={cn(
        "rounded-lg border border-border bg-card",
        "transition-colors focus-within:border-foreground/30",
      )}
    >
      {!compact ? (
        <div className="flex items-center gap-1 border-b border-border px-3 py-2">
          <PillButton icon={Briefcase} label="Matter" caret />
          <PillButton icon={Plus} label="Add sources" />
          <div className="ml-auto" />
          <PillButton icon={Paperclip} label="" iconOnly />
        </div>
      ) : null}

      <div className="flex items-end gap-2 p-2">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className={cn(
            "border-0 bg-transparent px-2 py-1.5 shadow-none",
            "focus-visible:ring-0",
            "min-h-[36px]",
          )}
        />
        <Button
          type="submit"
          size="icon"
          disabled={!canSend}
          aria-label="Send message"
          className="h-8 w-8 shrink-0 rounded-md"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </div>
    </form>
  );
}

interface PillButtonProps {
  icon: typeof Briefcase;
  label: string;
  caret?: boolean;
  iconOnly?: boolean;
}

function PillButton({ icon: Icon, label, caret, iconOnly }: PillButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium",
        "text-muted-foreground hover:bg-secondary hover:text-foreground",
        "transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {!iconOnly && label ? <span>{label}</span> : null}
      {caret ? <span className="text-muted-foreground/60">▾</span> : null}
    </button>
  );
}
