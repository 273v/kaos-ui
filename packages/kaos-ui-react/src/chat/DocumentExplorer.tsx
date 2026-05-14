/**
 * Right-side document explorer panel. One row per uploaded file with
 * filename + size + content type + token count + parse status, and a
 * collapsible body with the LLM-generated summary.
 *
 * Driven by `useSessionFiles` — but the host component does the
 * fetching and passes `files` here so this stays presentational.
 */

import { ChevronDown, ChevronRight, FileText, Loader2, X } from "lucide-react";
import { useState } from "react";

import type { FileMeta } from "../lib/files.js";

interface Props {
  open: boolean;
  onClose: () => void;
  files: FileMeta[];
  /** Pending state from the list query — shows a header spinner. */
  loading?: boolean;
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

function FileCard({ file }: { file: FileMeta }) {
  const [open, setOpen] = useState(false);
  const failed = file.parse.status === "failed";
  const hasSummary = !!file.summary;

  return (
    <li className="rounded-md border border-border bg-background">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3 py-2 hover:bg-muted/40 flex items-start gap-2"
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
      {open && (
        <div className="px-3 pb-3 pt-1 text-xs space-y-2">
          {failed && file.parse.error && (
            <div className="rounded-sm border border-destructive/40 bg-destructive/5 px-2 py-1 text-destructive">
              {file.parse.error}
            </div>
          )}
          {hasSummary ? (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                Summary
              </p>
              <p className="leading-relaxed text-foreground">{file.summary}</p>
            </div>
          ) : !failed ? (
            <p className="italic text-muted-foreground">
              No summary yet — the summarizer may have been offline at upload time.
            </p>
          ) : null}
        </div>
      )}
    </li>
  );
}

export function DocumentExplorer({ open, onClose, files, loading = false }: Props) {
  if (!open) return null;
  return (
    <aside
      className="w-80 flex-shrink-0 border-l border-border bg-card flex flex-col h-full"
      aria-label="Uploaded documents"
    >
      <header className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Documents</span>
          <span className="text-xs text-muted-foreground tabular-nums">{files.length}</span>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Close documents panel"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {files.length === 0 && !loading ? (
          <p className="text-xs text-muted-foreground italic">
            No documents uploaded yet. Drag a PDF, DOCX, or PPTX into the chat to add one.
          </p>
        ) : (
          <ul className="space-y-2 list-none p-0 m-0">
            {files.map((f) => (
              <FileCard key={f.filename} file={f} />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
