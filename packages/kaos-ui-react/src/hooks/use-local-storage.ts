/**
 * Tiny `useState`-shaped hook backed by `localStorage`. Survives
 * reloads + tab restores, falls through to `fallback` on first
 * mount + on any parse / storage error.
 *
 * Use for UI preferences (verbose-tools toggle, panel-open state)
 * that should persist between visits but don't warrant a server
 * round-trip. SSR-safe: returns `fallback` until the browser
 * `localStorage` is available.
 */

import { useCallback, useEffect, useState } from "react";

type SetState<T> = (next: T | ((prev: T) => T)) => void;

function readFromStorage<T>(key: string, fallback: T): T {
  if (typeof window === "undefined" || !window.localStorage) return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function useLocalStorage<T>(key: string, fallback: T): [T, SetState<T>] {
  // Lazy initializer reads once on mount — re-reads on key change via the
  // effect below. We avoid hydration mismatches on SSR by checking
  // `typeof window` inside the reader.
  const [value, setValue] = useState<T>(() => readFromStorage(key, fallback));

  // Re-read when `key` changes (rare but possible if a consumer keys
  // their state by sessionId or similar).
  // biome-ignore lint/correctness/useExhaustiveDependencies: fallback is intentionally NOT a dep — we only re-read on key changes; fallback shifts are not a re-read signal.
  useEffect(() => {
    setValue(readFromStorage(key, fallback));
  }, [key]);

  const update: SetState<T> = useCallback(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        try {
          if (typeof window !== "undefined" && window.localStorage) {
            window.localStorage.setItem(key, JSON.stringify(resolved));
          }
        } catch {
          // best-effort — Safari private mode, quota exceeded, etc.
        }
        return resolved;
      });
    },
    [key],
  );

  return [value, update];
}
