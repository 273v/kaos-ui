import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";
import type { SessionMeta } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function useSession(id: string) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: () => apiJson<SessionMeta>(`/v1/chat/sessions/${encodeURIComponent(id)}/meta`),
    enabled: Boolean(id),
  });
}
