/**
 * Bearer-token auth for the single-user-chat example.
 *
 * Flow: user types the kaos-agents bearer into the login form →
 * we save it to localStorage → probe an authenticated route to verify
 * → flip `isAuthenticated`. The token is then attached by `api-fetch.ts`
 * on every request.
 *
 * No httpOnly cookie because the kaos-agents bundled API uses bearer
 * auth and doesn't ship a cookie-issuing endpoint. Phase 4+ wraps with
 * cookie auth at the example level (see ARCHITECTURE.md § 4.5 OAQ-5).
 *
 * `login` / `refresh` return a boolean directly (same pattern as the
 * template): React state updates are async, so the router's
 * `beforeLoad` chains the boolean result, not `isAuthenticated`.
 */

import { createContext, type ReactNode, useCallback, useContext, useRef, useState } from "react";
import { clearToken, loadToken, saveToken } from "@/auth/storage";

export interface AuthContextValue {
  isAuthenticated: boolean;
  login: (token: string) => Promise<boolean>;
  logout: () => Promise<void>;
  refresh: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function _probe(token: string): Promise<boolean> {
  try {
    const response = await fetch("/v1/models", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return response.ok;
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const initial = loadToken() !== null;
  const [isAuthenticated, setAuthed] = useState(initial);
  const authedRef = useRef(initial);

  const setBoth = useCallback((value: boolean) => {
    authedRef.current = value;
    setAuthed(value);
  }, []);

  const login = useCallback(
    async (token: string): Promise<boolean> => {
      const trimmed = token.trim();
      if (!trimmed) {
        throw new Error("Token is required.");
      }
      const ok = await _probe(trimmed);
      if (!ok) {
        throw new Error("Token rejected by the server. Check your KAOS_AGENTS_API_API_TOKEN.");
      }
      saveToken(trimmed);
      setBoth(true);
      return true;
    },
    [setBoth],
  );

  const logout = useCallback(async () => {
    clearToken();
    setBoth(false);
  }, [setBoth]);

  const refresh = useCallback(async (): Promise<boolean> => {
    const token = loadToken();
    if (!token) {
      setBoth(false);
      return false;
    }
    const ok = await _probe(token);
    setBoth(ok);
    if (!ok) clearToken();
    return ok;
  }, [setBoth]);

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
