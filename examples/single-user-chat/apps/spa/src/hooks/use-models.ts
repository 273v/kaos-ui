import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api-fetch";
import type { ModelListResponse } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models(),
    queryFn: () => apiJson<ModelListResponse>("/v1/models"),
    staleTime: 5 * 60_000,
  });
}
