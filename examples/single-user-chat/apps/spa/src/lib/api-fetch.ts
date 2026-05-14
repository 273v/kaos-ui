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

export interface ApiError {
  status: number;
  what: string;
  how_to_fix?: string;
  alternative_tool?: string | null;
}

export async function apiFetch(input: string | URL, init: RequestInit = {}): Promise<Response> {
  const token = loadToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
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
    throw {
      status: response.status,
      what,
      how_to_fix: body.how_to_fix,
      alternative_tool: body.alternative_tool ?? null,
    } satisfies ApiError;
  }
  return response.json() as Promise<T>;
}
