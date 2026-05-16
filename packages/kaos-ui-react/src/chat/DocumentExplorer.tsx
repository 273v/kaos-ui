/**
 * Right-side document explorer panel. One row per uploaded file with
 * filename + size + content type + token count + parse status, and a
 * collapsible body with the LLM-generated summary.
 *
 * Driven by `useSessionFiles` — but the host component does the
 * fetching and passes `files` here so this stays presentational.
 */

import {
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  Loader2,
  MessageSquareQuote,
  RefreshCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { FileMeta } from "../lib/files.js";

/**
 * Payload for the "Ask about this" affordance — the doc-explorer's
 * inline highlight-to-prefill flow (F.9). The host receives both
 * the source filename and the verbatim selected passage; it's
 * responsible for routing this into the composer.
 *
 * Convention: passages > 600 chars get truncated by the host so
 * the prefill stays scannable inside the composer textarea. The
 * raw selection is passed through verbatim so the host can decide.
 */
export interface AskAboutSelection {
  filename: string;
  passage: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  files: FileMeta[];
  /** Pending state from the list query — shows a header spinner. */
  loading?: boolean;
  /**
   * Called when the user clicks the "Backfill" header action. The
   * button only renders when any ready-parsed file has a null
   * token_count or summary; pass undefined to hide it entirely.
   */
  onBackfill?: () => void;
  /** True while a backfill request is in flight. */
  backfilling?: boolean;
  /** Per-file: force a re-summarize. Receives the filename. */
  onResummarize?: (filename: string) => void;
  /** Filenames currently mid-resummarize — renders a spinner on those cards. */
  resummarizing?: ReadonlySet<string>;
  /**
   * Per-file: produce a download URL for the original bytes. When
   * provided, every ready file gets a Download icon link.
   *
   * **Deprecated in favor of `onDownload`.** A plain `<a href>` link
   * doesn't carry an Authorization header, so this prop breaks under
   * bearer-token auth (the request lands at the backend without
   * credentials and 401s). Cookie-auth deploys still work. New code
   * should pass `onDownload` which lets the host do an authenticated
   * fetch + blob download.
   */
  getDownloadUrl?: (filename: string) => string | null;
  /**
   * Per-file: fire an authenticated download. The host fetches the
   * file via its own `apiFetch` (which attaches Authorization / cookie
   * credentials) and triggers a browser save. When `onDownload` is
   * provided, the Download icon click calls it instead of dispatching
   * the `<a href>`.
   */
  onDownload?: (filename: string) => void | Promise<void>;
  /**
   * Highlight-to-Ask flow (F.9). Fires when the user selects text
   * inside a file's expanded summary and clicks the floating "Ask
   * about this" pill. The host wires this into the composer prefill
   * (typically a search-param-driven route navigation).
   */
  onAskAboutSelection?: (payload: AskAboutSelection) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTokens(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function FileCard({
  file,
  onResummarize,
  resummarizing,
  downloadUrl,
  onDownload,
  onAskAboutSelection,
}: {
  file: FileMeta;
  onResummarize?: (filename: string) => void;
  resummarizing?: boolean;
  downloadUrl?: string | null;
  onDownload?: (filename: string) => void | Promise<void>;
  onAskAboutSelection?: (payload: AskAboutSelection) => void;
}) {
  const [open, setOpen] = useState(false);
  const failed = file.parse.status === "failed";
  const hasSummary = !!file.summary;

  // Highlight-to-Ask state. We track the most recent selection scoped
  // to *this card's* summary container; cross-card selections are
  // ignored (the browser allows them but they're rarely intentional).
  const summaryRef = useRef<HTMLDivElement | null>(null);
  const [askPos, setAskPos] = useState<{ top: number; left: number } | null>(null);
  const [askText, setAskText] = useState<string>("");

  const clearAsk = useCallback(() => {
    setAskPos(null);
    setAskText("");
  }, []);

  // Document-level mouseup catches selection completion regardless of
  // where the mouse lifted (drag can exit + re-enter the container).
  useEffect(() => {
    if (!open || !onAskAboutSelection) return;
    const onMouseUp = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) {
        clearAsk();
        return;
      }
      // Require the selection to be ENTIRELY inside this card's
      // summary container — anchor + focus both contained.
      const root = summaryRef.current;
      if (!root) return;
      const anchor = sel.anchorNode;
      const focus = sel.focusNode;
      if (!anchor || !focus) {
        clearAsk();
        return;
      }
      if (!root.contains(anchor) || !root.contains(focus)) {
        clearAsk();
        return;
      }
      const text = sel.toString().trim();
      // Bail on trivial selections (< 4 chars or whitespace-only).
      if (text.length < 4) {
        clearAsk();
        return;
      }
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      const rootRect = root.getBoundingClientRect();
      // Position the pill just under the last line of the selection,
      // anchored to the card so it scrolls with the panel.
      setAskPos({
        top: rect.bottom - rootRect.top + 6,
        left: Math.min(rect.left - rootRect.left, rootRect.width - 140),
      });
      setAskText(text);
    };
    document.addEventListener("mouseup", onMouseUp);
    return () => document.removeEventListener("mouseup", onMouseUp);
  }, [open, onAskAboutSelection, clearAsk]);

  return (
    <li className="rounded-md border border-border bg-background">
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 min-w-0 text-left px-3 py-2 hover:bg-muted/40 flex items-start gap-2"
          aria-expanded={open}
        >
          <span className="mt-0.5 text-muted-foreground">
            {open ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
          </span>
          <span className="flex-1 min-w-0">
            <span className="block text-sm font-medium truncate" title={file.filename}>
              {file.filename}
            </span>
            <span className="block text-[11px] text-muted-foreground tabular-nums mt-0.5">
              {formatSize(file.size_bytes)}
              {file.content_type && ` · ${file.content_type}`}
              {typeof file.token_count === "number" && ` · ${formatTokens(file.token_count)} tok`}
              <span
                className={`ml-2 inline-block rounded-sm px-1 py-0.5 text-[9px] uppercase tracking-wide ${
                  failed ? "bg-destructive/20 text-destructive" : "bg-muted text-foreground/80"
                }`}
              >
                {failed ? "failed" : "ready"}
              </span>
            </span>
          </span>
        </button>
        <div className="flex items-center pr-2 gap-1">
          {onDownload ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                void onDownload(file.filename);
              }}
              title={`Download ${file.filename}`}
              aria-label={`Download ${file.filename}`}
              className="text-muted-foreground hover:text-foreground p-1"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          ) : downloadUrl ? (
            <a
              href={downloadUrl}
              download={file.filename}
              title={`Download ${file.filename}`}
              aria-label={`Download ${file.filename}`}
              className="text-muted-foreground hover:text-foreground p-1"
            >
              <Download className="h-3.5 w-3.5" />
            </a>
          ) : null}
          {onResummarize && !failed && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onResummarize(file.filename);
              }}
              disabled={resummarizing}
              title="Re-summarize this file"
              aria-label={`Re-summarize ${file.filename}`}
              className="text-muted-foreground hover:text-foreground p-1 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {resummarizing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
            </button>
          )}
        </div>
      </div>
      {open && (
        <div ref={summaryRef} className="relative px-3 pb-3 pt-1 text-xs space-y-2">
          {failed && file.parse.error && (
            <div className="rounded-sm border border-destructive/40 bg-destructive/5 px-2 py-1 text-destructive break-words">
              {file.parse.error}
            </div>
          )}
          {hasSummary ? (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                Summary
              </p>
              <p className="leading-relaxed text-foreground break-words selection:bg-accent/20">
                {file.summary}
              </p>
            </div>
          ) : !failed ? (
            <p className="italic text-muted-foreground">
              No summary yet — the summarizer may have been offline at upload time.
            </p>
          ) : null}
          {askPos && onAskAboutSelection && (
            <button
              type="button"
              onClick={() => {
                onAskAboutSelection({ filename: file.filename, passage: askText });
                window.getSelection()?.removeAllRanges();
                clearAsk();
              }}
              style={{ top: askPos.top, left: askPos.left }}
              className="absolute z-10 inline-flex items-center gap-1 rounded-md border border-accent/40 bg-card px-2 py-1 text-[11px] font-medium text-foreground shadow-sm hover:bg-accent/10 hover:border-accent/60 transition-colors"
              // mousedown handler prevents the underlying selection
              // from being cleared by the button's own click — without
              // this, the selection clears before our onClick fires.
              onMouseDown={(e) => e.preventDefault()}
              title="Ask the agent about this passage"
            >
              <MessageSquareQuote className="h-3 w-3 text-accent" />
              Ask about this
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function DocumentExplorer({
  open,
  onClose,
  files,
  loading = false,
  onBackfill,
  backfilling = false,
  onResummarize,
  resummarizing,
  getDownloadUrl,
  onDownload,
  onAskAboutSelection,
}: Props) {
  if (!open) return null;
  const needsBackfill = files.some(
    (f) => f.parse.status === "ready" && (f.summary == null || f.token_count == null),
  );
  return (
    <aside
      // `min-w-0` overrides the default `min-width: auto` in flexbox so the
      // aside actually respects its declared `w-80` (20rem) — without this,
      // a file with a long unbreakable token (URL, hash, etc.) in its summary
      // grows the column past 320px and collapses the chat column to 0.
      // `overflow-hidden` is the belt to that suspenders.
      className="w-80 flex-shrink-0 min-w-0 overflow-hidden border-l border-border bg-card flex flex-col h-full"
      aria-label="Uploaded documents"
    >
      <header className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Documents</span>
          <span className="text-xs text-muted-foreground tabular-nums">{files.length}</span>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex items-center gap-1">
          {onBackfill && needsBackfill && (
            <button
              type="button"
              onClick={onBackfill}
              disabled={backfilling}
              title="Recompute token counts + summaries for files that don't have them yet"
              aria-label="Backfill missing summaries"
              className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-2 py-1 rounded-md border border-border bg-card hover:bg-muted text-muted-foreground hover:text-foreground disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {backfilling ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              Backfill
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground ml-1"
            aria-label="Close documents panel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {files.length === 0 && !loading ? (
          <p className="text-xs text-muted-foreground italic">
            No documents uploaded yet. Drag a PDF, DOCX, or PPTX into the chat to add one.
          </p>
        ) : (
          <ul className="space-y-2 list-none p-0 m-0">
            {files.map((f) => (
              <FileCard
                key={f.filename}
                file={f}
                onResummarize={onResummarize}
                resummarizing={resummarizing?.has(f.filename)}
                downloadUrl={getDownloadUrl?.(f.filename)}
                onDownload={onDownload}
                onAskAboutSelection={onAskAboutSelection}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
