import { createContext, type ReactNode, useCallback, useContext, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-fetch";

/**
 * Auth state for the SPA.
 *
 * The actual session lives in an httpOnly cookie set by the backend on
 * `POST /v1/auth/login`. The frontend cannot read or write that cookie
 * — it only knows whether the most recent /v1/auth/me probe succeeded.
 *
 * IMPORTANT: ``login`` / ``refresh`` return a boolean directly. React
 * state updates from ``setAuthed`` are async and won't be visible to
 * a router ``beforeLoad`` running on the same microtask tick. The
 * ``_auth`` route guard reads the boolean return, not
 * ``isAuthenticated``, when chaining a refresh-then-check.
 */

export interface AuthContextValue {
  isAuthenticated: boolean;
  login: (token: string) => Promise<boolean>;
  logout: () => Promise<void>;
  refresh: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setAuthed] = useState(false);
  // Mirror in a ref so synchronous reads (router beforeLoad) see the
  // latest value without waiting for a re-render.
  const authedRef = useRef(false);

  const setBoth = useCallback((value: boolean) => {
    authedRef.current = value;
    setAuthed(value);
  }, []);

  const login = useCallback(
    async (token: string): Promise<boolean> => {
      const response = await apiFetch("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body?.detail?.what ?? "login failed");
      }
      setBoth(true);
      return true;
    },
    [setBoth],
  );

  const logout = useCallback(async () => {
    await apiFetch("/v1/auth/logout", { method: "POST" });
    setBoth(false);
  }, [setBoth]);

  const refresh = useCallback(async (): Promise<boolean> => {
    const response = await apiFetch("/v1/auth/me");
    const ok = response.ok;
    setBoth(ok);
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
