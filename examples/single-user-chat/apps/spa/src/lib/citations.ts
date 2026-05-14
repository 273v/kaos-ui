/**
 * Citation extraction API client + types (P2-1 backend).
 *
 * Backend endpoint: POST /v1/chat/sessions/{id}/citations
 *
 * Backed by `kaos_citations.extract_citations`. The wire-side
 * Citation shape is loose-typed here because the kaos-citations
 * union has 60+ kind variants — we model the common base fields
 * and accept everything else as `unknown`. The discriminator lives
 * on `kind`. See backend `app/routers/citations.py` + the
 * `Citation` model in the kaos-citations package.
 */

import { apiJson } from "@/lib/api-fetch";

/** Common base fields present on every Citation kind. */
export interface Citation {
  /** Discriminator: `cfr`, `case`, `statute`, `sec_filing`, etc. */
  kind: string;
  /** Exact substring from the source text (provenance). */
  raw: string;
  /** Canonical round-trip form (e.g. `17 CFR 240.10b-5`). */
  normalized: string;
  /** Character offsets in the source text — `[start, end]`. */
  span: [number, number];
  /** Stable per-extraction id (`c0001`, `c0002`, ...). */
  cite_id: string;
  /** Bluebook introductory signal (`see`, `accord`, `cf`, ...). */
  signal: string | null;
  /** Pinpoint citation (page / section / paragraph / footnote / star). */
  pin_cite: string | null;
  /** Optional originating document URI. */
  source_uri: string | null;
  /** Kind-specific fields land here. */
  [key: string]: unknown;
}

export interface ExtractCitationsResponse {
  session_id: string;
  count: number;
  citations: Citation[];
}

export async function extractCitations(
  sessionId: string,
  text: string,
): Promise<ExtractCitationsResponse> {
  return apiJson<ExtractCitationsResponse>(
    `/v1/chat/sessions/${encodeURIComponent(sessionId)}/citations`,
    {
      method: "POST",
      body: JSON.stringify({ text }),
    },
  );
}
