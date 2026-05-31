// TR-4 consumer: PATCH /v1/chat/sessions/:id/tool-set for tool policy
// changes — distinct from PATCH /meta so failures don't roll back
// title / model edits the user made in the same SettingsSheet save.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";
import type { SessionMeta, ToolSetUpdateBody } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function usePatchToolSet(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ToolSetUpdateBody) =>
      apiJson<SessionMeta>(`/v1/chat/sessions/${encodeURIComponent(sessionId)}/tool-set`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.session(sessionId), data);
      qc.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
  });
}
