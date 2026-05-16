/**
 * Bearer-token fetch wrapper used by every API call.
 *
 * Reads the token from localStorage (auth/storage.ts), attaches it as
 * `Authorization: Bearer …`, and unwraps JSON / errors.
 *
 * Why a wrapper:
 * - One place to deal with auth — Biome's `noRestrictedGlobals` in
 *   biome.json bans raw `fetch` to force every call through here.
 * - Per-request `signal` for abortable streams (used by useSendMessage).
 */

import { loadToken } from "@/auth/storage";

/**
 * Wire error from the FastAPI surface.
 *
 * Extends ``Error`` so callers using
 * ``mutation.error instanceof Error ? error.message : "fallback"`` (the
 * default React-Query + shadcn-toast pattern) get the server's ``what``
 * detail instead of falling through to a generic placeholder. Field
 * shape is preserved so callers that read ``.status`` / ``.what`` /
 * ``.how_to_fix`` directly still work.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly what: string;
  readonly how_to_fix?: string;
  readonly alternative_tool?: string | null;

  constructor(init: {
    status: number;
    what: string;
    how_to_fix?: string;
    alternative_tool?: string | null;
  }) {
    super(init.what);
    this.name = "ApiError";
    this.status = init.status;
    this.what = init.what;
    this.how_to_fix = init.how_to_fix;
    this.alternative_tool = init.alternative_tool ?? null;
  }
}

export async function apiFetch(input: string | URL, init: RequestInit = {}): Promise<Response> {
  const token = loadToken();
  // For multipart uploads (`body: FormData`) the browser must set
  // `Content-Type: multipart/form-data; boundary=...` itself — setting
  // a default `application/json` corrupts the parse and FastAPI 422s.
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  const headers: HeadersInit = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(init.headers ?? {}),
  };
  if (token) {
    (headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return fetch(input, { ...init, headers });
}

export async function apiJson<T>(input: string | URL, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(input, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Partial<ApiError> & {
      detail?: unknown;
    };
    const what =
      body.what ??
      (typeof body.detail === "string" ? body.detail : null) ??
      `HTTP ${response.status}`;
    throw new ApiError({
      status: response.status,
      what,
      how_to_fix: body.how_to_fix,
      alternative_tool: body.alternative_tool ?? null,
    });
  }
  return response.json() as Promise<T>;
}
