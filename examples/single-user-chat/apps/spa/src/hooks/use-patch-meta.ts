import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";
import type { PatchMetaBody, SessionMeta } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function usePatchMeta(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PatchMetaBody) =>
      apiJson<SessionMeta>(`/v1/chat/sessions/${encodeURIComponent(sessionId)}/meta`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.session(sessionId), data);
      qc.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
  });
}
