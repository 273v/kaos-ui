/**
 * Centralized fetch wrapper used by every API call.
 *
 * Why a single wrapper:
 * - `credentials: "include"` is mandatory for httpOnly-cookie auth.
 *   A single missing flag breaks auth across the app — see
 *   kaos-ui PATTERNS.md.
 * - Biome's `noRestrictedGlobals` (in biome.json) bans raw `fetch`
 *   in app code so an agent must reach for this helper.
 */

export interface ApiError {
  status: number;
  what: string;
  how_to_fix?: string;
  alternative_tool?: string | null;
}

export async function apiFetch(input: string | URL, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  return response;
}

export async function apiJson<T>(input: string | URL, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(input, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Partial<ApiError>;
    throw {
      status: response.status,
      what: body.what ?? `HTTP ${response.status}`,
      how_to_fix: body.how_to_fix,
      alternative_tool: body.alternative_tool ?? null,
    } satisfies ApiError;
  }
  return response.json() as Promise<T>;
}
