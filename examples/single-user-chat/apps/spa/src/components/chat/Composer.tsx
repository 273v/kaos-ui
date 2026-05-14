import { Textarea } from "@kaos-chat-example/ui/components/ui/textarea";
import { ArrowUp, Loader2, Paperclip, Square } from "lucide-react";
import { useEffect, useRef } from "react";

import { SUPPORTED_UPLOAD_ACCEPT } from "@/lib/files";

interface Props {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  /** Called when the user clicks Stop while a turn is in flight. */
  onStop?: () => void;
  pending: boolean;
  placeholder?: string;
  /** Left-of-send chip row (e.g., model picker). */
  leftChips?: React.ReactNode;
  /** Called once per file the user selects via the paperclip button. */
  onAttach?: (file: File) => void;
  /** True while an upload is in flight (disables the paperclip + shows a spinner). */
  uploading?: boolean;
}

/**
 * Bottom-sticky composer per UX-LANGUAGE.md § 4.3.
 * - max-w-3xl, narrower than the message column on purpose
 * - auto-grow textarea, Enter / Cmd-Enter sends, Shift-Enter newlines
 * - send arrow inside the textarea; flips to a stop button while pending
 * - chip row on the left: model picker (passed in), attach placeholder
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  pending,
  placeholder = "Send a message",
  leftChips,
  onAttach,
  uploading = false,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const attachEnabled = !!onAttach && !uploading;

  // Autogrow must run on every keystroke, not just mount. We don't
  // read `value` inside the effect, but its change is what makes the
  // DOM scrollHeight grow; biome's useExhaustiveDependencies strips
  // `value` from the deps because it isn't referenced inside. Explicit
  // suppression keeps the keystroke-driven autogrow correct.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `value` change is the SIGNAL to remeasure scrollHeight — not a dep we read.
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 280)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !pending;
  const showStop = pending && onStop != null;

  return (
    <div className="border-t border-border bg-background">
      <div className="mx-auto max-w-3xl px-4 pt-3 pb-2">
        <div className="flex items-center gap-2 pb-2">
          {leftChips}
          <input
            ref={fileInputRef}
            type="file"
            accept={SUPPORTED_UPLOAD_ACCEPT}
            multiple
            hidden
            onChange={(e) => {
              const files = e.target.files;
              if (!files || !onAttach) return;
              for (const file of Array.from(files)) onAttach(file);
              // Allow re-selecting the same file by clearing the input.
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={!attachEnabled}
            className={
              attachEnabled
                ? "flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                : "flex items-center gap-1 text-xs text-muted-foreground opacity-60 cursor-not-allowed"
            }
            title={
              uploading
                ? "Uploading…"
                : onAttach
                  ? "Attach a file (PDF, DOCX, PPTX)"
                  : "Attach unavailable"
            }
            aria-label="Attach file"
          >
            {uploading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Paperclip className="h-3 w-3" />
            )}
            {uploading ? "Uploading…" : "Attach"}
          </button>
        </div>
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
          {showStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              className={
                "absolute right-2 bottom-2 h-8 w-8 inline-flex items-center justify-center rounded-md " +
                "bg-secondary text-foreground hover:bg-muted border border-border"
              }
              title="Stop"
            >
              <Square className="h-3 w-3" fill="currentColor" />
            </button>
          ) : (
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
          )}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground text-center">
          AI output is informational. Not legal advice. Verify before relying.
        </p>
      </div>
    </div>
  );
}
