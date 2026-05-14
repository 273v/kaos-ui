// localStorage helpers for the bearer token.
//
// v1 auth (per ARCHITECTURE.md § 4.5): the SPA stores the kaos-agents
// bearer in localStorage and attaches it as `Authorization: Bearer …`
// on every request. We accept the XSS exposure for v1 simplicity.
// Phase 4+ revisits with httpOnly cookies wrapped around create_app().

const TOKEN_KEY = "kaos-chat-example.bearer";

export function loadToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(value: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, value);
  } catch {
    /* ignore — quota or privacy mode */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}
