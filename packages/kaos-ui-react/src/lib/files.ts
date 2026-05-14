/**
 * File-upload API client + wire types (matches the kaos-agents-flavored
 * backend in the single-user-chat example; see
 * `examples/single-user-chat/backend/app/models.py` for the Pydantic source).
 *
 * Hooks that use these helpers must be called inside a <KaosUIProvider>
 * because they read `transport` for URL + auth.
 */

import { type Transport, transportFetch, transportJson } from "./transport.js";

export interface FileParseStatus {
  status: "ready" | "failed";
  error: string | null;
}

export interface FileMeta {
  filename: string;
  size_bytes: number;
  content_type: string | null;
  uploaded_at: string;
  parse: FileParseStatus;
  /** Token count from kaos-nlp-core Tokenizer; null if tokenize failed. */
  token_count?: number | null;
  /** kaos-llm-core summary (~2-3 sentences); null if no LLM key / outage. */
  summary?: string | null;
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
 * Accept attribute for `<input type="file" accept>` — matches the
 * server-side supported_upload_extensions default. Consumers can
 * override.
 */
export const DEFAULT_UPLOAD_ACCEPT = ".pdf,.docx,.pptx";

export async function uploadFile(
  transport: Transport,
  sessionId: string,
  file: File,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await transportFetch(
    transport,
    `/sessions/${encodeURIComponent(sessionId)}/files`,
    { method: "POST", body: form },
  );
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

export function listFiles(transport: Transport, sessionId: string): Promise<FileListResponse> {
  return transportJson<FileListResponse>(
    transport,
    `/sessions/${encodeURIComponent(sessionId)}/files`,
  );
}

export interface BackfillResponse {
  /** Number of files whose token_count + summary were recomputed. */
  updated: number;
}

/**
 * Recompute token_count + summary for ready-parsed files that don't
 * have them yet (or pass `overwrite=true` to refresh everything,
 * `filename` to scope to a single file). Backed by the kaos-llm-core
 * summarize Program + the kaos-nlp-core tokenizer on the server.
 * Best-effort: a summarizer outage leaves the field null but never
 * errors the request.
 */
export function backfillFiles(
  transport: Transport,
  sessionId: string,
  options: { overwrite?: boolean; filename?: string } = {},
): Promise<BackfillResponse> {
  const params = new URLSearchParams();
  if (options.overwrite) params.set("overwrite", "true");
  if (options.filename) params.set("filename", options.filename);
  const qs = params.toString();
  const path = `/sessions/${encodeURIComponent(sessionId)}/files:backfill${qs ? `?${qs}` : ""}`;
  return transportJson<BackfillResponse>(transport, path, { method: "POST" });
}

export async function deleteFile(
  transport: Transport,
  sessionId: string,
  filename: string,
): Promise<void> {
  const response = await transportFetch(
    transport,
    `/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(filename)}`,
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
