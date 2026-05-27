/**
 * TanStack Query hook for the per-session VFS explorer.
 *
 * `useSessionVfs(sessionId, options)` — list query against
 * `GET /v1/chat/sessions/{id}/vfs`. Polls at 5s while enabled so the
 * panel reflects agent-written artifacts soon after they land
 * (v1 substitute for the deferred `vfs_changed` SSE event family —
 * see `kaos-modules/docs/plans/2026-05-26-spa-vfs-explorer-design.md`
 * Stage 2 deferral note).
 */

import { useQuery } from "@tanstack/react-query";

import { type ListVfsOptions, type VfsListResponse, listSessionVfs } from "../lib/vfs.js";
import { useTransport } from "../lib/transport.js";

const VFS_POLL_INTERVAL_MS = 5000;

const VFS_QUERY_PREFIX = "@273v/kaos-ui-react";

function vfsQueryKey(sessionId: string, options: ListVfsOptions) {
  // Stable key so toggling `includeSidecars` re-fetches cleanly.
  return [
    VFS_QUERY_PREFIX,
    "session",
    sessionId,
    "vfs",
    {
      prefix: options.prefix ?? "",
      recursive: options.recursive ?? true,
      maxDepth: options.maxDepth ?? null,
      pattern: options.pattern ?? null,
      includeSidecars: options.includeSidecars ?? false,
      cursor: options.cursor ?? null,
      limit: options.limit ?? null,
    },
  ] as const;
}

export interface UseSessionVfsOptions extends ListVfsOptions {
  /**
   * Whether the panel is currently visible. When false the query is
   * disabled so we don't poll the backend for closed panels.
   */
  enabled?: boolean;
  /**
   * Override the auto-refresh interval (ms). Default 5000ms — see
   * design doc Stage 2 deferral note. Pass `false` to disable polling.
   */
  refetchIntervalMs?: number | false;
}

export function useSessionVfs(sessionId: string | null, options: UseSessionVfsOptions = {}) {
  const transport = useTransport();
  const { enabled = true, refetchIntervalMs, ...listOptions } = options;
  const refetchInterval =
    refetchIntervalMs === false ? false : (refetchIntervalMs ?? VFS_POLL_INTERVAL_MS);

  return useQuery<VfsListResponse>({
    queryKey: vfsQueryKey(sessionId ?? "", listOptions),
    queryFn: () => listSessionVfs(transport, sessionId as string, listOptions),
    enabled: !!sessionId && enabled,
    refetchInterval,
    // The tree can shift mid-turn (agent writes artifacts); we want
    // the latest snapshot even when the query is stale.
    refetchOnWindowFocus: true,
  });
}
