// TR-4 consumer: fetch the registered tool categories for the
// SettingsSheet's Tool policy section.

import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/api-fetch";
import type { CategoriesResponse } from "@/lib/api-types";
import { queryKeys } from "@/lib/query-keys";

export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories(),
    queryFn: () => apiJson<CategoriesResponse>("/v1/chat/categories"),
    // The catalog is registered at backend startup and doesn't drift
    // during a session — cache aggressively to minimize fetches.
    staleTime: 30 * 60_000,
  });
}
