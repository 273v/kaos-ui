/**
 * File-upload API client + types (P1-1 / P1-2 backend).
 *
 * The backend serializes `FileMeta` / `FileParseStatus` / `UploadResponse`
 * / `FileListResponse` directly from its Pydantic models — these
 * mirror those shapes one-to-one. If the backend models change, the
 * compiler (or the `npx openapi-typescript` flow if/when we wire it
 * up) catches the drift.
 */

import { apiFetch, apiJson } from "@/lib/api-fetch";

export interface FileParseStatus {
  status: "ready" | "failed";
  error: string | null;
}

export interface FileMeta {
  filename: string;
  size_bytes: number;
  content_type: string | null;
  uploaded_at: string; // ISO-8601 datetime
  parse: FileParseStatus;
}

export interface UploadResponse {
  session_id: string;
  file: FileMeta;
  tools_enabled: boolean;
}

export interface FileListResponse {
  session_id: string;
  files: FileMeta[];
}

/**
 * Multipart upload to POST /v1/chat/sessions/{id}/files.
 *
 * Uses `apiFetch` directly so the FormData body keeps the browser-set
 * `Content-Type: multipart/form-data; boundary=…` header. `apiFetch`
 * detects `body instanceof FormData` and skips its default JSON
 * content-type — overriding it would corrupt the multipart parse and
 * FastAPI 422s on the missing `file` form field.
 */
export async function uploadFile(sessionId: string, file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file, file.name);

  const response = await apiFetch(`/v1/chat/sessions/${sessionId}/files`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: { what?: string; how_to_fix?: string } | string;
    };
    const detail = typeof body.detail === "object" ? body.detail : null;
    throw {
      status: response.status,
      what:
        detail?.what ?? (typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`),
      how_to_fix: detail?.how_to_fix,
    };
  }
  return (await response.json()) as UploadResponse;
}

export function listFiles(sessionId: string): Promise<FileListResponse> {
  return apiJson<FileListResponse>(`/v1/chat/sessions/${sessionId}/files`);
}

export async function deleteFile(sessionId: string, filename: string): Promise<void> {
  const response = await apiFetch(
    `/v1/chat/sessions/${sessionId}/files/${encodeURIComponent(filename)}`,
    { method: "DELETE" },
  );
  if (!response.ok && response.status !== 204) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: { what?: string; how_to_fix?: string } | string;
    };
    const detail = typeof body.detail === "object" ? body.detail : null;
    throw {
      status: response.status,
      what: detail?.what ?? `HTTP ${response.status}`,
      how_to_fix: detail?.how_to_fix,
    };
  }
}

export const SUPPORTED_UPLOAD_EXTENSIONS = [".pdf", ".docx", ".pptx"] as const;
export const SUPPORTED_UPLOAD_ACCEPT = SUPPORTED_UPLOAD_EXTENSIONS.join(",");
