/**
 * Right-side session VFS explorer panel. Shows the full session VFS
 * subtree (`sessions/{scoped}/**`) — peer of the Documents tab, not
 * a replacement. Operator-facing: surfaces agent-written artifacts,
 * the SPA's own toolcalls JSONL recorder output, and (opt-in) the
 * `.kaos.json` / `.meta.json` parse sidecars. See
 * `kaos-modules/docs/plans/2026-05-26-spa-vfs-explorer-design.md`.
 *
 * v1 is read-only: hover a node, see its full path + URI + size +
 * mime + parse status (for uploads). Click "show sidecars" to reveal
 * the SPA's internal parse intermediates.
 *
 * Driven by `useSessionVfs` polling at 5s — see the design doc's
 * Stage 2 deferral note for the SSE upgrade path.
 */

import {
  Boxes,
  ClipboardCopy,
  EyeOff,
  FileText,
  FolderTree,
  Loader2,
  RefreshCw,
  Settings2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { type VfsNode, groupVfsNodes } from "../lib/vfs.js";
import { EmptyState } from "./EmptyState.js";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Walk result nodes (already filtered + sorted by the backend). */
  nodes: VfsNode[];
  /** Pending state from the list query — shows a header spinner. */
  loading?: boolean;
  /** Error count from the walk result (rendered as a footer hint). */
  errorCount?: number;
  /** Whether sidecar entries are currently included in `nodes`. */
  showSidecars: boolean;
  /** Toggle for `showSidecars` (re-fires the query under the hood). */
  onShowSidecarsChange: (next: boolean) => void;
  /** Manual refresh (re-fires the query). */
  onRefresh?: () => void;
  /** True while a manual refresh is in flight. */
  refreshing?: boolean;
}

function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = new Date(iso);
  if (Number.isNaN(ts.getTime())) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - ts.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

function NodeBadge({ node }: { node: VfsNode }) {
  if (node.is_upload) {
    return (
      <span
        className="inline-flex items-center text-[9px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded-sm bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
        title="User-uploaded file"
      >
        upload
      </span>
    );
  }
  if (node.is_artifact) {
    return (
      <span
        className="inline-flex items-center text-[9px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded-sm bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300"
        title="Agent-written artifact"
      >
        artifact
      </span>
    );
  }
  if (node.is_sidecar) {
    return (
      <span
        className="inline-flex items-center text-[9px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded-sm bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
        title="SPA internal sidecar"
      >
        sidecar
      </span>
    );
  }
  return null;
}

function NodeRow({
  node,
  selected,
  onSelect,
}: {
  node: VfsNode;
  selected: boolean;
  onSelect: (n: VfsNode) => void;
}) {
  return (
    <li className="list-none p-0 m-0">
      <button
        type="button"
        onClick={() => onSelect(node)}
        className={`w-full text-left px-2 py-1.5 rounded-sm border transition-colors flex items-center gap-2 ${
          selected
            ? "border-accent bg-accent/10"
            : "border-transparent hover:border-border hover:bg-muted/30"
        }`}
      >
        <FileText className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
        <span className="text-xs font-mono truncate flex-1" title={node.relative_path}>
          {node.relative_path}
        </span>
        <span className="text-[10px] text-muted-foreground tabular-nums flex-shrink-0">
          {formatSize(node.size_bytes)}
        </span>
        <NodeBadge node={node} />
      </button>
    </li>
  );
}

function PreviewPane({ node }: { node: VfsNode | null }) {
  const [copied, setCopied] = useState(false);
  if (!node) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground p-4 text-center">
        Select a node from the tree to preview its metadata.
      </div>
    );
  }
  return (
    <div className="flex-1 overflow-y-auto px-3 py-3 text-xs">
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="font-mono text-[11px] break-all" title={node.relative_path}>
          {node.relative_path}
        </span>
        <NodeBadge node={node} />
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
        <dt className="text-muted-foreground">Path</dt>
        <dd className="flex items-center gap-1.5 min-w-0">
          <code className="font-mono text-[10px] truncate flex-1" title={node.path}>
            {node.path}
          </code>
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(node.path);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }}
            className="inline-flex items-center text-muted-foreground hover:text-foreground flex-shrink-0"
            title="Copy full VFS path"
            aria-label="Copy full VFS path"
          >
            <ClipboardCopy className="h-3 w-3" />
          </button>
          {copied && (
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400">copied</span>
          )}
        </dd>
        <dt className="text-muted-foreground">Size</dt>
        <dd className="tabular-nums">{formatSize(node.size_bytes)}</dd>
        <dt className="text-muted-foreground">MIME</dt>
        <dd className="font-mono text-[10px] break-all">{node.mime_type ?? "—"}</dd>
        <dt className="text-muted-foreground">Modified</dt>
        <dd>{formatRelativeTime(node.modified_at)}</dd>
        {node.parse_status && (
          <>
            <dt className="text-muted-foreground">Parse</dt>
            <dd>
              <span
                className={`inline-flex items-center text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded-sm ${
                  node.parse_status === "ready"
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                    : node.parse_status === "failed"
                      ? "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {node.parse_status}
              </span>
            </dd>
          </>
        )}
      </dl>
      {node.summary_excerpt && (
        <div className="mt-3 rounded-md border border-border bg-muted/30 p-2 text-[11px] leading-relaxed">
          <div className="text-[9px] uppercase tracking-wide text-muted-foreground mb-1">
            Summary
          </div>
          {node.summary_excerpt}
        </div>
      )}
    </div>
  );
}

export function VfsExplorer({
  open,
  onClose,
  nodes,
  loading = false,
  errorCount = 0,
  showSidecars,
  onShowSidecarsChange,
  onRefresh,
  refreshing = false,
}: Props) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const groups = useMemo(() => groupVfsNodes(nodes), [nodes]);
  const selectedNode = useMemo(
    () => nodes.find((n) => n.path === selectedPath) ?? null,
    [nodes, selectedPath],
  );

  if (!open) return null;

  // The backend's stable sort already orders groups (uploads →
  // artifacts → other → sidecars); preserve that by iterating in
  // insertion order from `groupVfsNodes`.
  const orderedGroupLabels = Array.from(groups.keys());

  return (
    <aside
      className="w-96 flex-shrink-0 min-w-0 overflow-hidden border-l border-border bg-card flex flex-col h-full"
      aria-label="Session VFS explorer"
    >
      <header className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <FolderTree className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">VFS</span>
          <span className="text-xs text-muted-foreground tabular-nums">{nodes.length}</span>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onShowSidecarsChange(!showSidecars)}
            title={
              showSidecars
                ? "Hide internal .kaos.json / .meta.json sidecars"
                : "Show internal .kaos.json / .meta.json sidecars"
            }
            aria-label={showSidecars ? "Hide sidecars" : "Show sidecars"}
            className={`inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-2 py-1 rounded-md border ${
              showSidecars
                ? "border-accent text-accent bg-accent/10"
                : "border-border text-muted-foreground hover:text-foreground hover:bg-muted"
            }`}
          >
            {showSidecars ? <Settings2 className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
            Sidecars
          </button>
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              title="Refresh VFS tree"
              aria-label="Refresh VFS tree"
              className="inline-flex items-center text-muted-foreground hover:text-foreground disabled:opacity-60 disabled:cursor-not-allowed px-1.5 py-1"
            >
              {refreshing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground ml-1"
            aria-label="Close VFS panel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-1/2 min-w-0 overflow-y-auto px-2 py-2 border-r border-border">
          {nodes.length === 0 && !loading ? (
            <EmptyState
              icon={<Boxes className="h-6 w-6" />}
              title="VFS is empty"
              description={
                showSidecars
                  ? "No files yet — upload a document or run a turn that writes artifacts."
                  : "No user-visible files yet — toggle Sidecars to see SPA internals."
              }
            />
          ) : (
            <ul className="space-y-2 list-none p-0 m-0">
              {orderedGroupLabels.map((label) => {
                const groupNodes = groups.get(label) ?? [];
                return (
                  <li key={label || "(root)"} className="list-none p-0 m-0">
                    {label && (
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground px-1 mb-1">
                        {label}/
                      </div>
                    )}
                    <ul className="space-y-0.5 list-none p-0 m-0">
                      {groupNodes.map((n) => (
                        <NodeRow
                          key={n.path}
                          node={n}
                          selected={selectedPath === n.path}
                          onSelect={(node) => setSelectedPath(node.path)}
                        />
                      ))}
                    </ul>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <PreviewPane node={selectedNode} />
      </div>

      <footer className="px-3 py-2 border-t border-border text-[10px] text-muted-foreground flex items-center justify-between">
        <span>{nodes.length} entries</span>
        {errorCount > 0 && (
          <span className="text-amber-700 dark:text-amber-400">
            {errorCount} walk error{errorCount === 1 ? "" : "s"}
          </span>
        )}
      </footer>
    </aside>
  );
}
