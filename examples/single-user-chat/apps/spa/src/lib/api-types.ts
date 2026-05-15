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

export interface SessionToolSetWire {
  allowed_groups: string[];
  denied_tools: string[];
  auto_narrow: boolean;
}

export interface SessionMeta {
  id: string;
  title: string;
  model: string;
  system_prompt: string;
  tools_enabled: boolean;
  tool_set: SessionToolSetWire;
  created_at: string;
  last_message_at: string | null;
  message_count: number;
  archived: boolean;
  starred: boolean;
  title_source: "manual" | "auto";
}

// TR-4: GET /v1/chat/categories row + PATCH .../tool-set body.

export interface CategoryInfo {
  id: string;
  label: string;
  description: string;
  default_enabled: boolean;
  tool_count: number;
}

export interface CategoriesResponse {
  categories: CategoryInfo[];
}

export interface ToolSetUpdateBody {
  allowed_groups?: string[];
  denied_tools?: string[];
  auto_narrow?: boolean;
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

export interface HistoryToolCall {
  id: string;
  name: string;
  status: "running" | "done" | "error";
  args_preview?: string | null;
  result_preview?: string | null;
}

export interface HistoryMessageEntry {
  role: "user" | "assistant" | "system";
  content: string;
  added_at: number;
  tool_calls?: HistoryToolCall[];
}

export interface PatchMetaBody {
  title?: string;
  model?: string;
  system_prompt?: string;
  tools_enabled?: boolean;
  starred?: boolean;
}
