import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api-fetch";
import type { SessionListResponse } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function useSessionList(archived = false) {
  return useQuery({
    queryKey: [...queryKeys.sessions(), { archived }],
    queryFn: () => apiJson<SessionListResponse>(`/v1/chat/sessions?archived=${archived}`),
  });
}
