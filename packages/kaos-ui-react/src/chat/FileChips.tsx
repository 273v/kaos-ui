/**
 * Row of compact chips above the composer — one per uploaded file in
 * the current session. Each chip: filename, size, parse-status pill
 * (ready / failed), X button to delete. Parse failures get a red ring
 * + tooltip with the error.
 *
 * Long file lists get capped at `maxVisible` (default 3) with a
 * "+N more" pill that calls `onShowAll` — typically wired to open
 * the <DocumentExplorer> panel.
 */

import { ChevronRight, Loader2, X } from "lucide-react";
import { useMemo } from "react";

import type { FileMeta } from "../lib/files.js";

interface Props {
  files: FileMeta[];
  onRemove: (filename: string) => void;
  /** Filenames currently mid-delete (renders a spinner instead of X). */
  removing?: Set<string>;
  /** Maximum number of inline chips before collapsing to "+N more". */
  maxVisible?: number;
  /** Called when the user clicks the overflow pill. Typically opens the explorer. */
  onShowAll?: () => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileChips({ files, onRemove, removing, maxVisible = 3, onShowAll }: Props) {
  // Failed files are pinned to the front of the visible window — they're
  // the ones the user is most likely to want to retry/delete. Ready
  // files fill the remaining slots in upload order.
  const ordered = useMemo(() => {
    const failed = files.filter((f) => f.parse.status === "failed");
    const ready = files.filter((f) => f.parse.status !== "failed");
    return [...failed, ...ready];
  }, [files]);

  if (ordered.length === 0) return null;

  const visible = ordered.slice(0, maxVisible);
  const overflow = ordered.length - visible.length;

  return (
    <ul
      aria-label={`Uploaded files (${files.length})`}
      className="flex flex-wrap items-center gap-2 mb-2 list-none p-0 m-0"
    >
      {visible.map((f) => {
        const failed = f.parse.status === "failed";
        const isRemoving = removing?.has(f.filename) === true;
        return (
          <li
            key={f.filename}
            className={
              failed
                ? "inline-flex items-center gap-2 rounded-full border border-destructive/40 bg-destructive/5 px-2.5 py-1 text-xs"
                : "inline-flex items-center gap-2 rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs"
            }
            title={failed && f.parse.error ? `Parse failed: ${f.parse.error}` : f.filename}
          >
            <span className="font-medium text-foreground max-w-[14rem] truncate">{f.filename}</span>
            <span className="text-muted-foreground tabular-nums">{formatSize(f.size_bytes)}</span>
            <span
              className={
                failed
                  ? "rounded-sm bg-destructive/20 text-destructive px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
                  : "rounded-sm bg-muted text-foreground/80 px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
              }
            >
              {failed ? "failed" : "ready"}
            </span>
            <button
              type="button"
              onClick={() => onRemove(f.filename)}
              disabled={isRemoving}
              aria-label={`Remove ${f.filename}`}
              className="text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRemoving ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <X className="h-3 w-3" />
              )}
            </button>
          </li>
        );
      })}
      {overflow > 0 && (
        <li>
          <button
            type="button"
            onClick={onShowAll}
            disabled={!onShowAll}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-60 disabled:cursor-default"
            title={
              onShowAll
                ? "Show all uploaded documents"
                : `${overflow} more file${overflow === 1 ? "" : "s"}`
            }
            aria-label={`Show ${overflow} more file${overflow === 1 ? "" : "s"}`}
          >
            +{overflow} more
            {onShowAll && <ChevronRight className="h-3 w-3" />}
          </button>
        </li>
      )}
    </ul>
  );
}
