/**
 * Citation extraction API client + types. Backed by the kaos-citations
 * extract endpoint at POST /sessions/{id}/citations.
 *
 * The wire-side Citation shape is loose-typed because the kaos-citations
 * kind union has 60+ variants. We model the common base fields and
 * accept everything else as `unknown`. The discriminator is `kind`.
 */

import { type Transport, transportJson } from "./transport.js";

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

export function extractCitations(
  transport: Transport,
  sessionId: string,
  text: string,
): Promise<ExtractCitationsResponse> {
  return transportJson<ExtractCitationsResponse>(
    transport,
    `/sessions/${encodeURIComponent(sessionId)}/citations`,
    { method: "POST", body: JSON.stringify({ text }) },
  );
}
