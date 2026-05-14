/**
 * TanStack Query hooks for the per-session file surface (P1-1 / P1-2).
 *
 * `useSessionFiles(sessionId)`        — list query
 * `useUploadFile(sessionId)`          — upload mutation; invalidates the
 *                                       list query AND the session meta
 *                                       query (tools_enabled flips)
 * `useDeleteFile(sessionId)`          — delete mutation; same invalidation
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteFile,
  type FileListResponse,
  listFiles,
  type UploadResponse,
  uploadFile,
} from "@/lib/files";
import { queryKeys } from "@/lib/query-keys";

export function useSessionFiles(sessionId: string | null) {
  return useQuery<FileListResponse>({
    queryKey: queryKeys.sessionFiles(sessionId ?? ""),
    queryFn: () => listFiles(sessionId as string),
    enabled: !!sessionId,
  });
}

export function useUploadFile(sessionId: string | null) {
  const qc = useQueryClient();
  return useMutation<UploadResponse, unknown, File>({
    mutationFn: (file) => {
      if (!sessionId) {
        return Promise.reject(new Error("session id is required for upload"));
      }
      return uploadFile(sessionId, file);
    },
    onSuccess: () => {
      if (!sessionId) return;
      // Refresh the file list and the session meta (tools_enabled
      // may have flipped on the first upload).
      qc.invalidateQueries({ queryKey: queryKeys.sessionFiles(sessionId) });
      qc.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      qc.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
  });
}

export function useDeleteFile(sessionId: string | null) {
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: (filename) => {
      if (!sessionId) {
        return Promise.reject(new Error("session id is required for delete"));
      }
      return deleteFile(sessionId, filename);
    },
    onSuccess: () => {
      if (!sessionId) return;
      qc.invalidateQueries({ queryKey: queryKeys.sessionFiles(sessionId) });
    },
  });
}
