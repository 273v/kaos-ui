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

  // ``uploading`` is plumbed in for the paperclip spinner; also block
  // Send so the user can't fire a turn while an attachment is still in
  // flight (otherwise the agent answers "I don't see any uploaded
  // file" right after the user dropped one in).
  const canSend = value.trim().length > 0 && !pending && !uploading;
  const showStop = pending && onStop != null;
  const sendTitle = uploading
    ? "Waiting for upload to finish…"
    : pending
      ? "Stop generating"
      : "Send (Enter)";

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
                  ? "Attach a file (PDF, DOCX, PPTX, XLSX)"
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
            // Bigger min-height + body-size (15px) typography so the
            // composer reads like a draft surface, not a settings
            // input. 11rem max keeps it from eating the chat column
            // before "Stop" / overflow scroll kick in.
            className="w-full resize-none min-h-[72px] max-h-[280px] pr-14 px-3.5 py-2.5 text-[15px] leading-[1.55] rounded-lg border border-input bg-background placeholder:text-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
          />
          {showStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop generating"
              // h-10 w-10 = 40px touch target (WCAG 2.5.8 AA minimum
              // for desktop is 24px, but mobile recommendation is
              // 44px; 40 is a sane middle).
              className="absolute right-2.5 bottom-2.5 h-10 w-10 inline-flex items-center justify-center rounded-md bg-muted text-foreground hover:bg-muted/80 border border-border transition-colors"
              title="Stop"
            >
              <Square className="h-3.5 w-3.5" fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!canSend}
              aria-label="Send"
              title={sendTitle}
              className="absolute right-2.5 bottom-2.5 h-10 w-10 inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="mt-2.5 text-[11px] text-foreground/45 text-center tabular-nums">{footnote}</p>
      </div>
    </div>
  );
}
