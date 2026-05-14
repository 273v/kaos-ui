import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api-fetch";
import type { CreateSessionBody, SessionMeta } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateSessionBody) =>
      apiJson<SessionMeta>("/v1/chat/sessions", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
  });
}
