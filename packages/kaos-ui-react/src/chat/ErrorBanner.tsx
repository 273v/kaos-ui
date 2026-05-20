/**
 * Shared error-state banner with optional retry + dismiss.
 *
 * Closes #317 (C.4 — Error + recovery states). Single visual
 * treatment for "something went wrong" surfaces across the panels.
 *
 * Composition:
 *   - Leading destructive-tinted ⚠ icon
 *   - Single-line error message (truncated with title for full text)
 *   - Optional retry button
 *   - Optional dismiss × button
 *
 * The banner uses `role="alert"` + `aria-live="polite"` so screen
 * readers announce it the first time it appears in a turn but don't
 * re-announce on every re-render. Two tone variants:
 *
 *   - ``severity="error"`` (default) — destructive border + bg
 *   - ``severity="warning"`` — amber tones for recoverable conditions
 */

import { AlertTriangle, RefreshCw, X } from "lucide-react";

interface Props {
  /** Required: what went wrong. One short sentence. */
  message: string;
  /** Optional: how to fix / context. Renders below the message. */
  detail?: string;
  /** Fire on retry — when omitted, no retry button appears. */
  onRetry?: () => void;
  /** Whether a retry is in flight. Disables the button + shows spinner. */
  retrying?: boolean;
  /** Fire on dismiss — when omitted, no × button appears. */
  onDismiss?: () => void;
  /** Tone — "error" (red) or "warning" (amber). Default "error". */
  severity?: "error" | "warning";
  /** Extra className. */
  className?: string;
}

export function ErrorBanner({
  message,
  detail,
  onRetry,
  retrying = false,
  onDismiss,
  severity = "error",
  className = "",
}: Props) {
  const palette =
    severity === "warning"
      ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-200"
      : "border-destructive/40 bg-destructive/5 text-destructive";
  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${palette} ${className}`}
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="font-medium break-words" title={message}>
          {message}
        </p>
        {detail && (
          <p className="mt-0.5 text-[11px] opacity-80 break-words" title={detail}>
            {detail}
          </p>
        )}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] uppercase tracking-wide border border-current/40 hover:bg-current/10 disabled:opacity-60 disabled:cursor-not-allowed"
          aria-label="Retry"
        >
          <RefreshCw className={`h-3 w-3 ${retrying ? "animate-spin" : ""}`} aria-hidden="true" />
          Retry
        </button>
      )}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="text-current opacity-70 hover:opacity-100"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
