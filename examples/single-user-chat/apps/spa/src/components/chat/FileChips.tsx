// FileChips — row of compact chips above the composer, one per
// uploaded file in the current session.
//
// Each chip carries: filename, size, parse-status pill (ready /
// failed), and an X button to delete. Parse failures get a red ring
// + tooltip with the error message. Empty (no files) renders null
// to avoid pushing the composer down with a blank row.

import { Loader2, X } from "lucide-react";

import type { FileMeta } from "@/lib/files";

interface Props {
  files: FileMeta[];
  onRemove: (filename: string) => void;
  removing?: Set<string>;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileChips({ files, onRemove, removing }: Props) {
  if (files.length === 0) return null;

  return (
    <ul
      aria-label={`Uploaded files (${files.length})`}
      className="flex flex-wrap items-center gap-2 mb-2 list-none p-0 m-0"
    >
      {files.map((f) => {
        const failed = f.parse.status === "failed";
        const isRemoving = removing?.has(f.filename) === true;
        return (
          <li
            key={f.filename}
            className={
              failed
                ? "inline-flex items-center gap-2 rounded-full border border-red-300/70 bg-red-50/40 px-2.5 py-1 text-xs"
                : "inline-flex items-center gap-2 rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs"
            }
            title={failed && f.parse.error ? `Parse failed: ${f.parse.error}` : f.filename}
          >
            <span className="font-medium text-foreground max-w-[14rem] truncate">{f.filename}</span>
            <span className="text-muted-foreground tabular-nums">{formatSize(f.size_bytes)}</span>
            <span
              className={
                failed
                  ? "rounded-sm bg-red-100 text-red-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
                  : "rounded-sm bg-emerald-100 text-emerald-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
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
    </ul>
  );
}
