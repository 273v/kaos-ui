import { Textarea } from "@kaos-chat-example/ui/components/ui/textarea";
import { ArrowUp, Paperclip } from "lucide-react";
import { useEffect, useRef } from "react";

interface Props {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  pending: boolean;
  placeholder?: string;
  /** Left-of-send chip row (e.g., model picker). */
  leftChips?: React.ReactNode;
}

/**
 * Bottom-sticky composer per UX-LANGUAGE.md § 4.3.
 * - max-w-3xl, narrower than the message column on purpose
 * - auto-grow textarea, Enter / Cmd-Enter sends, Shift-Enter newlines
 * - send arrow inside the textarea
 * - chip row on the left: model picker (passed in), attach placeholder
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  pending,
  placeholder = "Send a message",
  leftChips,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  // Auto-grow.
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 280)}px`;
  }, []);

  const canSend = value.trim().length > 0 && !pending;

  return (
    <div className="border-t border-border bg-background">
      <div className="mx-auto max-w-3xl px-4 pt-3 pb-2">
        {(leftChips || true) && (
          <div className="flex items-center gap-2 pb-2">
            {leftChips}
            <button
              type="button"
              disabled
              className="flex items-center gap-1 text-xs text-muted-foreground opacity-60 cursor-not-allowed"
              title="Coming soon"
            >
              <Paperclip className="h-3 w-3" />
              Attach
            </button>
          </div>
        )}
        <div className="relative">
          <Textarea
            ref={taRef}
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (canSend) onSubmit();
              }
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                if (canSend) onSubmit();
              }
            }}
            rows={1}
            className="resize-none min-h-[56px] max-h-[280px] pr-12 leading-relaxed"
          />
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSend}
            aria-label="Send"
            className={
              "absolute right-2 bottom-2 h-8 w-8 inline-flex items-center justify-center rounded-md " +
              "bg-primary text-primary-foreground hover:bg-primary/90 " +
              "disabled:opacity-50 disabled:cursor-not-allowed"
            }
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground text-center">
          AI output is informational. Not legal advice. Verify before relying.
        </p>
      </div>
    </div>
  );
}
