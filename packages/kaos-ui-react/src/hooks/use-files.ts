/**
 * TanStack Query hooks for the per-session file surface.
 *
 * `useSessionFiles(sessionId)`  — list query (auto-fetches on session id change)
 * `useUploadFile(sessionId)`    — upload mutation; invalidates the file list
 * `useDeleteFile(sessionId)`    — delete mutation; invalidates the file list
 *
 * Consumers that have additional caches to invalidate (e.g. a session
 * meta query that holds `tools_enabled`) can pass `onSuccess` callbacks
 * via the standard TanStack Query options route; or they can invalidate
 * their own keys in a wrapping `onSuccess` after `mutate(file)`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type BackfillResponse,
  type FileListResponse,
  type UploadResponse,
  backfillFiles,
  deleteFile,
  listFiles,
  uploadFile,
} from "../lib/files.js";
import { kaosQueryKeys } from "../lib/query-keys.js";
import { useTransport } from "../lib/transport.js";

export function useSessionFiles(sessionId: string | null) {
  const transport = useTransport();
  return useQuery<FileListResponse>({
    queryKey: kaosQueryKeys.files(sessionId ?? ""),
    queryFn: () => listFiles(transport, sessionId as string),
    enabled: !!sessionId,
  });
}

export function useUploadFile(sessionId: string | null) {
  const transport = useTransport();
  const qc = useQueryClient();
  return useMutation<UploadResponse, unknown, File>({
    mutationFn: (file) => {
      if (!sessionId) {
        return Promise.reject(new Error("session id is required for upload"));
      }
      return uploadFile(transport, sessionId, file);
    },
    onSuccess: () => {
      if (!sessionId) return;
      qc.invalidateQueries({ queryKey: kaosQueryKeys.files(sessionId) });
    },
  });
}

export function useDeleteFile(sessionId: string | null) {
  const transport = useTransport();
  const qc = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: (filename) => {
      if (!sessionId) {
        return Promise.reject(new Error("session id is required for delete"));
      }
      return deleteFile(transport, sessionId, filename);
    },
    onSuccess: () => {
      if (!sessionId) return;
      qc.invalidateQueries({ queryKey: kaosQueryKeys.files(sessionId) });
    },
  });
}

export function useBackfillFiles(sessionId: string | null) {
  const transport = useTransport();
  const qc = useQueryClient();
  return useMutation<BackfillResponse, unknown, { overwrite?: boolean } | undefined>({
    mutationFn: (vars) => {
      if (!sessionId) {
        return Promise.reject(new Error("session id is required for backfill"));
      }
      return backfillFiles(transport, sessionId, vars ?? {});
    },
    onSuccess: () => {
      if (!sessionId) return;
      qc.invalidateQueries({ queryKey: kaosQueryKeys.files(sessionId) });
    },
  });
}
