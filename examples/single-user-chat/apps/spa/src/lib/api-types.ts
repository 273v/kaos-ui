// Mirrors of the backend's Pydantic shapes in `backend/app/models.py`.
// Phase 2 task #19 replaces this with a generated client from openapi-ts.

export interface ModelEntry {
  id: string;
  label: string;
  provider: "anthropic" | "openai" | "google" | "xai";
  context_window?: number | null;
  recommended_for?: string | null;
}

export interface ModelListResponse {
  models: ModelEntry[];
}

export interface SessionMeta {
  id: string;
  title: string;
  model: string;
  system_prompt: string;
  tools_enabled: boolean;
  created_at: string;
  last_message_at: string | null;
  message_count: number;
  archived: boolean;
  starred: boolean;
  title_source: "manual" | "auto";
}

export interface SessionSummary {
  id: string;
  title: string;
  model: string;
  last_message_at: string | null;
  created_at: string;
  message_count: number;
  archived: boolean;
  starred: boolean;
  title_source: "manual" | "auto";
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  next_cursor: string | null;
}

export interface CreateSessionBody {
  title?: string;
  model?: string;
  system_prompt?: string;
  tools_enabled?: boolean;
}

export interface PatchMetaBody {
  title?: string;
  model?: string;
  system_prompt?: string;
  tools_enabled?: boolean;
  starred?: boolean;
}
