export interface Document {
  id: string;
  name: string;
  mime_type: string;
  size: number;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface SearchResult {
  document: Document;
  score: number;
  snippet: string;
}
