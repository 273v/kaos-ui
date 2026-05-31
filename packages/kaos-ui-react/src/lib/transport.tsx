/**
 * Transport abstraction + <KaosUIProvider> React context.
 *
 * Every hook + component in this package reads its backend coordinates
 * from the nearest `<KaosUIProvider transport={...}>`. The provider
 * encapsulates:
 *
 *   - `baseUrl`         — prefix for every request (`/v1/chat`, etc.)
 *   - `getToken()`      — bearer token getter (localStorage, cookie, …)
 *   - `fetch`           — optional override; defaults to global fetch
 *
 * Hooks that need a specific endpoint (`POST /sessions/{id}/messages`,
 * `POST /sessions/{id}/files`, ...) compose the URL on top of the
 * transport. Apps with a different backend shape can bypass the
 * built-in hooks and call `transport.fetch()` directly.
 *
 * The provider must wrap every component in this package. We surface
 * a helpful error from `useTransport()` if it's used outside.
 */

import { createContext, type ReactNode, useContext, useMemo } from "react";

export interface Transport {
  /**
   * URL prefix for every request — typically `/v1/chat` or the full
   * origin of a remote backend. Does NOT need a trailing slash; the
   * helper joins paths with a single `/`.
   */
  baseUrl: string;
  /**
   * Optional bearer token getter. Returning `null` skips the
   * `Authorization` header. Called per-request so the consumer can
   * rotate tokens without remounting.
   */
  getToken?: () => string | null | undefined;
  /**
   * Optional fetch impl — useful for tests (msw, fetch-mock) or for
   * apps that wrap fetch with retry/circuit-breaker logic. Defaults
   * to the global `fetch`.
   */
  fetch?: typeof fetch;
}

const TransportContext = createContext<Transport | null>(null);

export interface KaosUIProviderProps {
  transport: Transport;
  children: ReactNode;
}

export function KaosUIProvider({ transport, children }: KaosUIProviderProps) {
  // Memo so a parent re-render with the same fields doesn't invalidate
  // the context for every consumer. Consumers should pass a stable
  // transport object (or memoize it themselves) — but we protect
  // against the common footgun anyway by keying on the addressable
  // fields rather than the whole object identity.
  const { baseUrl, getToken, fetch: customFetch } = transport;
  const stable = useMemo<Transport>(
    () => ({ baseUrl, getToken, fetch: customFetch }),
    [baseUrl, getToken, customFetch],
  );
  return <TransportContext.Provider value={stable}>{children}</TransportContext.Provider>;
}

/**
 * Read the current `Transport` from context. Throws a helpful error
 * if the caller forgot to mount `<KaosUIProvider>` somewhere above.
 */
export function useTransport(): Transport {
  const t = useContext(TransportContext);
  if (!t) {
    throw new Error(
      "useTransport(): no <KaosUIProvider> in tree. Wrap your app in " +
        "<KaosUIProvider transport={{ baseUrl, getToken }}>...</KaosUIProvider>.",
    );
  }
  return t;
}

/**
 * Join `transport.baseUrl` + `path`, normalizing the boundary slash.
 * Exported for hooks/components that need to build their own URL.
 */
export function joinUrl(transport: Transport, path: string): string {
  const base = transport.baseUrl.endsWith("/") ? transport.baseUrl.slice(0, -1) : transport.baseUrl;
  const tail = path.startsWith("/") ? path : `/${path}`;
  return `${base}${tail}`;
}

/**
 * Authenticated `fetch` for arbitrary endpoints. Adds:
 *   - `Authorization: Bearer <token>` if `transport.getToken()` returns one
 *   - `Content-Type: application/json` UNLESS the body is `FormData`
 *     (in which case the browser must set the multipart boundary)
 *
 * Returns the raw `Response` — callers parse JSON or stream the body
 * themselves so we don't pre-commit a body-handling strategy.
 */
export async function transportFetch(
  transport: Transport,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = joinUrl(transport, path);
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...((init.headers as Record<string, string>) ?? {}),
  };
  const token = transport.getToken?.();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const f = transport.fetch ?? globalThis.fetch;
  return f(url, { ...init, headers });
}

/**
 * Convenience JSON helper: GET/POST/etc. and parse the response body
 * as JSON. Throws an `ApiError`-shaped object on non-2xx so consumers
 * can `try/catch` without sniffing `response.ok`.
 */
export interface ApiError {
  status: number;
  what: string;
  how_to_fix?: string;
  alternative_tool?: string | null;
}

export async function transportJson<T>(
  transport: Transport,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await transportFetch(transport, path, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Partial<ApiError> & {
      detail?: unknown;
    };
    const detailObj =
      typeof body.detail === "object" && body.detail
        ? (body.detail as Record<string, unknown>)
        : null;
    const what =
      body.what ??
      (detailObj && typeof detailObj.what === "string" ? detailObj.what : null) ??
      (typeof body.detail === "string" ? body.detail : null) ??
      `HTTP ${response.status}`;
    const how_to_fix =
      body.how_to_fix ??
      (detailObj && typeof detailObj.how_to_fix === "string" ? detailObj.how_to_fix : undefined);
    throw {
      status: response.status,
      what,
      how_to_fix,
      alternative_tool: body.alternative_tool ?? null,
    } satisfies ApiError;
  }
  return (await response.json()) as T;
}
