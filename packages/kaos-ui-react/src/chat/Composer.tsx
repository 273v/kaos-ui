/**
 * Bottom-sticky composer. Auto-grow textarea, Enter / Cmd-Enter sends,
 * Shift-Enter newlines. Send arrow inside the textarea; flips to a
 * stop button while a turn is in flight.
 *
 * Optional `leftChips` slot for app-specific affordances (model picker,
 * temperature chip, etc.). Optional `onAttach` enables the paperclip
 * button + hidden file input.
 *
 * Pure presentational — wire to `useSendMessage` / `useUploadFile` at
 * the route level.
 */

import { ArrowUp, Loader2, Paperclip, Square } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";

import { DEFAULT_UPLOAD_ACCEPT } from "../lib/files.js";

export interface ComposerProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  /** Called when the user clicks Stop while a turn is in flight. */
  onStop?: () => void;
  pending: boolean;
  placeholder?: string;
  /** Left-of-send chip row (e.g., model picker). */
  leftChips?: ReactNode;
  /** Called once per file the user selects via the paperclip button. */
  onAttach?: (file: File) => void;
  /** True while an upload is in flight (disables paperclip + shows spinner). */
  uploading?: boolean;
  /** Accept attribute for the file input; defaults to .pdf,.docx,.pptx. */
  accept?: string;
  /** Footer text under the composer. Defaults to a generic disclaimer. */
  footnote?: string;
}

const DEFAULT_FOOTNOTE = "AI output is informational. Verify before relying.";

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
  accept = DEFAULT_UPLOAD_ACCEPT,
  footnote = DEFAULT_FOOTNOTE,
}: ComposerProps) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const attachEnabled = !!onAttach && !uploading;

  // biome-ignore lint/correctness/useExhaustiveDependencies: `value` change is the signal to remeasure scrollHeight — we don't read it inside.
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
            id="composer-attach"
            name="composer-attach"
            type="file"
            accept={accept}
            multiple
            hidden
            aria-label="Attach files to message"
            onChange={(e) => {
              const files = e.target.files;
              if (!files || !onAttach) return;
              for (const file of Array.from(files)) onAttach(file);
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
          <textarea
            ref={taRef}
            id="composer-message"
            name="composer-message"
            aria-label="Message"
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
            className="w-full resize-none min-h-[56px] max-h-[280px] pr-12 px-3 py-2 leading-relaxed rounded-md border border-input bg-background text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          />
          {showStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              className="absolute right-2 bottom-2 h-8 w-8 inline-flex items-center justify-center rounded-md bg-muted text-foreground hover:bg-muted/80 border border-border"
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
              className="absolute right-2 bottom-2 h-8 w-8 inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground text-center">{footnote}</p>
      </div>
    </div>
  );
}
