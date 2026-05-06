import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useState,
} from "react";
import { apiFetch } from "@/lib/api-fetch";

/**
 * Auth state for the SPA.
 *
 * The actual session lives in an httpOnly cookie set by the backend on
 * `POST /v1/auth/login`. The frontend cannot read or write that cookie
 * — it only knows whether the most recent /v1/auth/me probe succeeded.
 */

export interface AuthContextValue {
  isAuthenticated: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setAuthed] = useState(false);

  const login = useCallback(async (token: string) => {
    const response = await apiFetch("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail?.what ?? "login failed");
    }
    setAuthed(true);
  }, []);

  const logout = useCallback(async () => {
    await apiFetch("/v1/auth/logout", { method: "POST" });
    setAuthed(false);
  }, []);

  const refresh = useCallback(async () => {
    const response = await apiFetch("/v1/auth/me");
    setAuthed(response.ok);
  }, []);

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
