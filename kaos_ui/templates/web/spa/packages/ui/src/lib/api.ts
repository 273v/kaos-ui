import type { Document, SearchResult } from "../types/document.js";

const API_URL = import.meta.env.VITE_API_URL ?? "/api/v1";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export function fetchHealth(): Promise<{ status: string }> {
  return apiFetch("/health");
}

export function fetchDocuments(): Promise<Document[]> {
  return apiFetch("/documents");
}

export function searchDocuments(query: string): Promise<SearchResult[]> {
  return apiFetch(`/documents/search?q=${encodeURIComponent(query)}`);
}
