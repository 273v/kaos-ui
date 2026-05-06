import { useQuery } from "@tanstack/react-query";
import { fetchDocuments } from "../lib/api.js";
import type { Document } from "../types/document.js";

export function useDocuments() {
  return useQuery<Document[]>({
    queryKey: ["documents"],
    queryFn: fetchDocuments,
  });
}
