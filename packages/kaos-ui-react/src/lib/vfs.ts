/**
 * Session VFS explorer API client + wire types.
 *
 * Mirrors the backend Pydantic models in
 * `examples/single-user-chat/backend/app/models.py` (`VfsNode`,
 * `VfsListResponse`) and the route surface in `app/routers/vfs.py`.
 *
 * The VFS explorer is a peer of the Documents tab: Documents shows the
 * lawyer-facing "files I uploaded" view; the VFS panel shows the full
 * agent-visible state under `sessions/{scoped}/**` for operator
 * debugging. See `kaos-modules/docs/plans/2026-05-26-spa-vfs-explorer-design.md`.
 */

import { type Transport, transportFetch } from "./transport.js";

export type VfsNodeKind = "file" | "directory";

export interface VfsNode {
  path: string;
  relative_path: string;
  kind: VfsNodeKind;
  size_bytes: number | null;
  mime_type: string | null;
  created_at: string | null;
  modified_at: string | null;
  is_sidecar: boolean;
  is_upload: boolean;
  is_artifact: boolean;
  parse_status: "ready" | "pending" | "failed" | null;
  summary_excerpt: string | null;
}

export interface VfsListResponse {
  session_id: string;
  prefix: string;
  nodes: VfsNode[];
  total_count: number;
  error_count: number;
  next_cursor: string | null;
}

export interface ListVfsOptions {
  prefix?: string;
  recursive?: boolean;
  maxDepth?: number;
  pattern?: string;
  includeSidecars?: boolean;
  cursor?: string;
  limit?: number;
}

/**
 * GET `/sessions/{id}/vfs` — walk the session VFS subtree.
 *
 * Throws a normalized error object `{status, what, how_to_fix?}` on
 * non-2xx so consumers can render the agent-friendly error triple.
 */
export async function listSessionVfs(
  transport: Transport,
  sessionId: string,
  options: ListVfsOptions = {},
): Promise<VfsListResponse> {
  const params = new URLSearchParams();
  if (options.prefix) params.set("prefix", options.prefix);
  if (options.recursive === false) params.set("recursive", "false");
  if (options.maxDepth !== undefined) params.set("max_depth", String(options.maxDepth));
  if (options.pattern) params.set("pattern", options.pattern);
  if (options.includeSidecars) params.set("include_sidecars", "true");
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit !== undefined) params.set("limit", String(options.limit));

  const query = params.toString();
  const path = `/sessions/${encodeURIComponent(sessionId)}/vfs${query ? `?${query}` : ""}`;
  const response = await transportFetch(transport, path, { method: "GET" });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: { what?: string; how_to_fix?: string } | string;
    };
    const detail = typeof body.detail === "object" ? body.detail : null;
    throw {
      status: response.status,
      what:
        detail?.what ?? (typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`),
      how_to_fix: detail?.how_to_fix,
    };
  }
  return (await response.json()) as VfsListResponse;
}

/**
 * Group nodes by their first relative-path segment for tree rendering.
 *
 * The backend already sorts uploads → artifacts → other → sidecars, so
 * we preserve the order — this helper just collects siblings under a
 * common parent label.
 */
export function groupVfsNodes(nodes: VfsNode[]): Map<string, VfsNode[]> {
  const groups = new Map<string, VfsNode[]>();
  for (const node of nodes) {
    const rel = node.relative_path;
    const slash = rel.indexOf("/");
    const head = slash === -1 ? "" : rel.slice(0, slash);
    const arr = groups.get(head) ?? [];
    arr.push(node);
    groups.set(head, arr);
  }
  return groups;
}
