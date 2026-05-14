import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";
import { queryKeys } from "@/lib/query-keys";

export function useArchiveSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiJson<{ ok: true; archived_at: string }>(
        `/v1/chat/sessions/${encodeURIComponent(sessionId)}/archive`,
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
  });
}
