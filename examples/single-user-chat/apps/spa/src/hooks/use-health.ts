import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";

export interface HealthResponse {
  status: string;
  /**
   * Short SHA of the currently-deployed build (12-char sha256 over
   * installed kaos-* package versions). Used by the sidebar to badge
   * sessions whose `meta.build_sha` differs from this value — i.e.,
   * sessions created on an older deployment whose behavior may
   * predate a known fix.
   *
   * Stable for the lifetime of the running process. Changes only on
   * restart with a different package version set.
   *
   * See: kaos-modules/docs/plans/2026-05-18-cross-layer-issue-inventory.md § P3-10.
   */
  build_sha?: string;
}

/**
 * Subscribe to the backend's `/v1/health` endpoint.
 *
 * The query is set to a long stale time because the build SHA is
 * immutable for the process's lifetime — the only way it changes is
 * if the backend is restarted with a different wheel set, and the
 * SPA itself will reload (or hit a real connection error) in that
 * case.
 */
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiJson<HealthResponse>("/v1/health"),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
    retry: 1,
  });
}
