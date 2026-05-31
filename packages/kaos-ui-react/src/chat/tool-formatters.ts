/**
 * Tool-call presentation helpers.
 *
 * Wire-side `ToolCallSummary` ships only the raw tool id (`kaos-source-
 * fr-search`), an optional `args_preview` string, and an optional
 * `result_preview` that's typically a one-line human summary followed
 * by a `\n\n` and a 200-byte JSON tail. Stuffing that into a chip
 * verbatim looks like a debug log; the user has to read JSON to know
 * what happened.
 *
 * This module derives a *presentation* from those raw fields:
 *
 *   `formatToolCall({ name, args_preview, result_preview })` →
 *   {
 *     label:           "Federal Register · Search",
 *     args_summary:    "cybersecurity disclosure 2024 · type=Rule · since 2024-01-01",
 *     result_summary:  "9 documents — top: EDGAR Filer Access (2024-30494)",
 *     result_records:  [ {document_number, title, agency, publication_date, html_url}, ... ],
 *     result_kind:     "fr_search",
 *   }
 *
 * The `ToolCallBlock` consumes the presentation: name → header label,
 * args_summary → header chip, result_summary → header → arrow, expanded
 * body renders `result_records` as a typed structured view when present,
 * with a "raw" toggle for the source JSON.
 *
 * Unknown tools degrade gracefully — they get a title-cased label
 * derived from the id, the args+result strings show in monospace
 * blocks, and nothing breaks.
 */

import type { ToolCallSummary } from "../lib/chat-state.js";

// ---------------------------------------------------------------------------
// Public shape
// ---------------------------------------------------------------------------

export interface FormattedToolCall {
  /** Human label e.g. "Federal Register · Search". Always set. */
  label: string;
  /** Compact one-line summary of the args. May be empty. */
  args_summary: string;
  /** Compact one-line summary of the result. May be empty. */
  result_summary: string;
  /**
   * Parsed structured records the expanded view can render as cards
   * instead of a JSON blob. Empty when the result couldn't be parsed
   * or the tool isn't in the formatter registry.
   */
  result_records: Record<string, unknown>[];
  /** Discriminator for the expanded view ("fr_search", "doc", etc.). */
  result_kind: ResultKind;
  /** Lead-in text from the result before the JSON blob, e.g. "Found 9 documents." */
  result_lead: string;
  /** Raw JSON tail (string) when present, for the "Show raw" affordance. */
  result_raw_json?: string;
  /**
   * True when the tool's payload was an ``{"error": true, ...}``
   * envelope. The wire ``status`` is still ``"done"`` for tools that
   * returned an error envelope rather than raising, so callers should
   * branch on this flag (not ``call.status``) when deciding whether to
   * render the destructive icon + clean failure label in the chip
   * header.
   */
  is_error_envelope?: boolean;
  /** Structured error fields recovered from ``{"error": true, ...}``. */
  error?: {
    message: string;
    locator?: string;
    http_status?: number;
    /** Short host-style label for the chip header, e.g. "finance.yahoo.com". */
    locator_host?: string;
    /** One-word reason like "retryable HTTP", "404", "blocked". */
    reason?: string;
  };
}

export type ResultKind =
  | "fr_search"
  | "fr_doc"
  | "fr_content"
  | "ecfr_section"
  | "fetch_url"
  | "markdown_parse"
  | "pdf_extract"
  | "unknown";

// ---------------------------------------------------------------------------
// Tool id → human label registry
// ---------------------------------------------------------------------------

const TOOL_LABELS: Record<string, string> = {
  "kaos-source-fr-search": "Federal Register · Search",
  "kaos-source-fr-get-content": "Federal Register · Fetch full text",
  "kaos-source-fr-get-document": "Federal Register · Fetch metadata",
  "kaos-source-ecfr-content": "eCFR · Fetch section",
  "kaos-source-ecfr-search-structure": "eCFR · Search by structure",
  "kaos-source-fetch-url": "Fetch URL",
  "kaos-source-preview": "Preview file",
  "kaos-content-parse-markdown": "Parse Markdown",
  "kaos-content-parse-html": "Parse HTML",
  "kaos-pdf-extract-parse": "PDF · Extract text",
  "kaos-pdf-extract-tables": "PDF · Extract tables",
  "kaos-agent-chat": "Sub-agent · Chat",
  "kaos-agent-findings": "Sub-agent · Findings",
  "kaos-agent-memory-query": "Memory · Read",
  "kaos-agent-memory-search": "Memory · Search",
};

/**
 * Friendly label for a tool id. Falls back to a title-cased
 * humanization of the id when not in the registry.
 *
 * "kaos-source-fr-search" → "Federal Register · Search"
 * "kaos-future-tool-x"    → "Future Tool X"
 */
export function toolLabel(toolId: string): string {
  const hit = TOOL_LABELS[toolId];
  if (hit) return hit;
  // Strip kaos- / kaos_ prefix, title-case the rest.
  const stripped = toolId.replace(/^kaos[-_]/, "").replace(/[-_]/g, " ");
  return stripped.replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Result parser — wire format from kaos-agents tool_call_summary
// ---------------------------------------------------------------------------

/**
 * Split a wire `result_preview` into its human lead-in + JSON tail.
 *
 * kaos-agents serializes tool results as
 *
 *   <one-line human summary>\n\n<json or text blob>
 *
 * where the blob may be truncated at 200 chars (so trailing JSON is
 * usually invalid). We keep `lead` for the chip header and try to
 * JSON.parse `raw` so the expanded body can render structured cards
 * when the truncation happened to land on a brace boundary.
 */
function splitResultPreview(preview: string | undefined): { lead: string; raw?: string } {
  if (!preview) return { lead: "" };
  const idx = preview.indexOf("\n\n");
  if (idx === -1) return { lead: preview.trim() };
  return {
    lead: preview.slice(0, idx).trim(),
    raw: preview.slice(idx + 2).trim(),
  };
}

function safeJsonParse<T = unknown>(raw: string | undefined): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

/**
 * Repair-and-parse: returns whatever fields can be recovered from a
 * truncated JSON blob.
 *
 * kaos-agents truncates wire `result_summary` at ~200 chars, which
 * usually lands inside a string value of the FIRST inner record. The
 * naive `JSON.parse` refuses the whole payload, so the user sees raw
 * text where they should see structured fields.
 *
 * Strategy: walk the input tracking depth + string state. Each time
 * we cross a structural boundary at the right depth — a closing brace
 * or a comma after a value — we record the position as "safe to
 * truncate at". When we reach EOF (or a partial string we can't close)
 * we truncate at the last safe boundary, drop a trailing comma if any,
 * append closing braces to match the still-open structures, and parse.
 *
 * Example: a 200-char truncation of
 *   ``{"results": [{"document_number": "2024-30494", "title": "EDGAR
 *     Filer Access...", "type": "Rule", "publication_date""``
 * is repaired to
 *   ``{"results": [{"document_number": "2024-30494", "title": "EDGAR
 *     Filer Access...", "type": "Rule"}]}``
 * and parses cleanly — the user sees 3 fields of the first record
 * instead of an unparseable blob.
 */
export function repairAndParseJson<T = unknown>(raw: string | undefined): T | null {
  if (!raw) return null;
  // Fast path: parse as-is.
  try {
    return JSON.parse(raw) as T;
  } catch {
    /* fall through to repair */
  }

  // Walk the string, find the last position we can safely truncate at.
  let depth = 0;
  let inString = false;
  let escaped = false;
  let lastSafePos = -1;
  // Track the opening character of each level so we know how to close.
  const opens: string[] = [];

  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (inString) {
      if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
        // Don't mark lastSafePos here — a closed string could be a
        // KEY (`"foo":`) with no value yet, which won't parse with
        // appended closers. Only the structural tokens below — `,`,
        // `}`, `]`, numbers, and true/false/null — are
        // unambiguously "this value is complete" boundaries.
      }
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{" || ch === "[") {
      opens.push(ch);
      depth++;
    } else if (ch === "}" || ch === "]") {
      opens.pop();
      depth--;
      // After a balanced close, the position right after it is
      // unambiguously safe.
      lastSafePos = i + 1;
    } else if (ch === "," && depth > 0) {
      // After a comma at depth >= 1, the position is safe — we
      // can drop the comma and any partial field that follows.
      lastSafePos = i;
    } else if ((ch === "t" || ch === "f" || ch === "n") && depth > 0) {
      // true / false / null literals — best-effort detection.
      // Find the end of the literal.
      const literals = { t: "true", f: "false", n: "null" } as const;
      const word = literals[ch as keyof typeof literals];
      if (raw.slice(i, i + word.length) === word) {
        // After consuming, position is safe.
        lastSafePos = i + word.length;
        i += word.length - 1;
      }
    } else if (/[0-9-]/.test(ch as string) && depth > 0) {
      // Number literal. Consume digits / decimal / exponent.
      let j = i;
      while (j < raw.length && /[0-9eE+.-]/.test(raw[j] as string)) {
        j++;
      }
      lastSafePos = j;
      i = j - 1;
    }
  }

  if (lastSafePos <= 0 || opens.length === 0) return null;

  // Build the repaired candidate.
  let candidate = raw.slice(0, lastSafePos).trimEnd();
  if (candidate.endsWith(",")) {
    candidate = candidate.slice(0, -1).trimEnd();
  }
  // Re-balance: walk the candidate to figure out which structures
  // remain open, then append matching closers in reverse order.
  const stillOpen: string[] = [];
  let inStr = false;
  let esc = false;
  for (const c of candidate) {
    if (esc) {
      esc = false;
      continue;
    }
    if (inStr) {
      if (c === "\\") esc = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') inStr = true;
    else if (c === "{") stillOpen.push("}");
    else if (c === "[") stillOpen.push("]");
    else if (c === "}" || c === "]") stillOpen.pop();
  }
  if (inStr) {
    // We're inside a string at the end of the candidate. Drop the
    // trailing open quote + everything between it and the previous
    // boundary. We can detect this by walking back to the last comma
    // / open-brace / open-bracket and truncating there.
    let cutoff = -1;
    for (let i = candidate.length - 1; i >= 0; i--) {
      const c = candidate[i];
      if (c === "," || c === "{" || c === "[") {
        cutoff = i + (c === "," ? 0 : 1);
        break;
      }
    }
    if (cutoff <= 0) return null;
    candidate = candidate.slice(0, cutoff).trimEnd();
    if (candidate.endsWith(",")) candidate = candidate.slice(0, -1).trimEnd();
  }
  candidate = candidate + stillOpen.reverse().join("");

  try {
    return JSON.parse(candidate) as T;
  } catch {
    return null;
  }
}

/**
 * Walk a string and yield every balanced top-level ``{…}`` object that
 * parses as JSON. Used to recover an array of records from a truncated
 * `{"results": [{...}, {...}, {...}]` blob — `JSON.parse` would refuse
 * the whole thing because the trailing string was cut mid-character;
 * this returns whatever fully-closed objects sit inside it.
 *
 * Tracks brace depth and skips over string literals (with backslash
 * escapes) so braces inside string values don't trip the boundary.
 */
function extractBalancedObjects<T = Record<string, unknown>>(raw: string): T[] {
  const out: T[] = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (inString) {
      if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0 && start !== -1) {
        const slice = raw.slice(start, i + 1);
        try {
          out.push(JSON.parse(slice) as T);
        } catch {
          /* skip — not a valid object */
        }
        start = -1;
      } else if (depth < 0) {
        depth = 0;
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Per-family formatters
// ---------------------------------------------------------------------------

interface FrSearchResult {
  results?: Array<Record<string, unknown>>;
  count?: number;
}

function formatFrSearch(
  lead: string,
  raw: string | undefined,
): { args: string; summary: string; records: Record<string, unknown>[] } {
  // Try the well-formed parse first; fall back to extracting balanced
  // record objects from a truncated array. kaos-agents truncates
  // result_preview at ~200 chars, which usually slices the trailing
  // record mid-string — we still want to surface the records that
  // DID make it through intact.
  const parsed = safeJsonParse<FrSearchResult>(raw) ?? repairAndParseJson<FrSearchResult>(raw);
  let records: Record<string, unknown>[] = Array.isArray(parsed?.results)
    ? (parsed.results as Record<string, unknown>[])
    : [];
  if (records.length === 0 && raw) {
    records = extractBalancedObjects<Record<string, unknown>>(raw);
  }
  const top = records[0];
  const topTitle = (top?.title as string | undefined) ?? "";
  const topDoc = (top?.document_number as string | undefined) ?? "";
  // Lead is e.g. "Found 9 Federal Register document(s), showing 9"
  // — keep just the counts; trim the verbose noun.
  const condensed = lead
    .replace(/Federal Register document\(s\)/, "documents")
    .replace(/\s+/g, " ")
    .trim();
  const summary = top ? `${condensed} — top: ${topTitle} (${topDoc})` : condensed || "no results";
  return {
    args: "",
    summary,
    records,
  };
}

function formatFrContent(
  lead: string,
  raw: string | undefined,
): { args: string; summary: string; records: Record<string, unknown>[] } {
  const parsed = safeJsonParse<Record<string, unknown>>(raw);
  const docNumber = (parsed?.document_number as string | undefined) ?? "";
  // Lead is "Regulation S-P: ... — 50000 chars (text) (truncated)"
  // — split into the title and the size annotation so we can render
  // them as separate emphasis levels.
  const m = lead.match(/^(?<title>.+?)\s+—\s+(?<size>.+?)$/);
  const title = m?.groups?.title ?? lead;
  const size = m?.groups?.size ?? "";
  const summary = size ? `${title} · ${size}` : title;
  return {
    args: docNumber ? `doc ${docNumber}` : "",
    summary,
    records: parsed ? [parsed] : [],
  };
}

function formatFetchUrl(
  lead: string,
  raw: string | undefined,
): { args: string; summary: string; records: Record<string, unknown>[] } {
  const parsed = safeJsonParse<Record<string, unknown>>(raw);
  const url = (parsed?.url as string | undefined) ?? "";
  // Lead is "Fetched <filename> (10.3 KB)"
  const summary = lead.replace(/^Fetched\s+/, "");
  return {
    args: url ? new URL(url, "https://x").host : "",
    summary,
    records: parsed ? [parsed] : [],
  };
}

function formatEcfrSection(
  lead: string,
  raw: string | undefined,
): { args: string; summary: string; records: Record<string, unknown>[] } {
  const parsed = safeJsonParse<Record<string, unknown>>(raw);
  const title = parsed?.title;
  const section = parsed?.section;
  const argsBits = [title ? `Title ${title}` : "", section ? `§${section}` : ""].filter(Boolean);
  return {
    args: argsBits.join(" "),
    summary: lead,
    records: parsed ? [parsed] : [],
  };
}

function formatGeneric(
  lead: string,
  raw: string | undefined,
): { args: string; summary: string; records: Record<string, unknown>[] } {
  const parsed =
    safeJsonParse<Record<string, unknown>>(raw) ??
    repairAndParseJson<Record<string, unknown>>(raw) ??
    extractBalancedObjects<Record<string, unknown>>(raw ?? "")[0] ??
    null;
  return {
    args: "",
    // Empty when there's literally nothing — that's the signal for the
    // chip header to fall back to "running…" or just hide the arrow.
    summary: lead,
    records: parsed ? [parsed] : [],
  };
}

// ---------------------------------------------------------------------------
// Args parser — best-effort
// ---------------------------------------------------------------------------

/**
 * Tool args_preview comes through as a string. Sometimes it's JSON
 * (from `tool_call_args_delta` deltas) and sometimes it's empty
 * (lossy fallback path from memory/actions). When JSON-parseable,
 * render as `key=value` pairs trimmed to fit a chip header.
 */
function formatArgsPreview(args: string | undefined): string {
  if (!args) return "";
  const parsed = safeJsonParse<Record<string, unknown>>(args);
  if (!parsed || typeof parsed !== "object") {
    // Not parseable: return the first 80 chars.
    return args.length > 80 ? `${args.slice(0, 80)}…` : args;
  }
  const pairs: string[] = [];
  for (const [k, v] of Object.entries(parsed)) {
    if (v == null || v === "") continue;
    let rendered: string;
    if (typeof v === "string") {
      rendered = v.length > 40 ? `"${v.slice(0, 40)}…"` : `"${v}"`;
    } else if (Array.isArray(v)) {
      rendered = `[${v.length}]`;
    } else if (typeof v === "object") {
      rendered = "{…}";
    } else {
      rendered = String(v);
    }
    pairs.push(`${k}=${rendered}`);
  }
  return pairs.join(" · ").slice(0, 140);
}

// ---------------------------------------------------------------------------
// Top-level format
// ---------------------------------------------------------------------------

/**
 * Detect a kaos error envelope in the wire preview.
 *
 * KAOS tools that fail without raising return a JSON payload shaped
 * ``{"error": true, "message": "<human msg>", "locator"?: "<url|path>",
 * "http_status"?: 404, ...}`` on the result wire. The wire ``status``
 * stays ``"done"`` because the tool returned successfully — it just
 * returned a failure. Detect this so the chip can render a clean
 * "FAILED · <host> · <reason>" header instead of dumping the raw
 * JSON into the title.
 *
 * Returns ``null`` when the preview is not a recognisable error
 * envelope (covers both successful tool calls and old wire formats).
 */
export function extractErrorEnvelope(preview: string | undefined): {
  message: string;
  locator?: string;
  http_status?: number;
  locator_host?: string;
  reason?: string;
} | null {
  if (!preview) return null;
  const trimmed = preview.trim();
  if (!trimmed.startsWith("{")) return null;
  // Cheap pre-check to avoid parsing every payload.
  if (!trimmed.includes('"error"')) return null;
  let payload: Record<string, unknown> | null = null;
  try {
    payload = JSON.parse(trimmed) as Record<string, unknown>;
  } catch {
    // Preview is often truncated mid-JSON / mid-string (kaos-agents
    // chops at ~200 chars without quote-balancing). First try a strict
    // match for a closed string, then fall back to "everything from
    // the opening quote to end of preview" so we still surface the
    // first chunk of the human message + locator in the chip header.
    const closedMessage = trimmed.match(/"message"\s*:\s*"((?:[^"\\]|\\.)*)"/);
    const closedLocator = trimmed.match(/"locator"\s*:\s*"((?:[^"\\]|\\.)*)"/);
    const openMessage = trimmed.match(/"message"\s*:\s*"((?:[^"\\]|\\.)*)$/);
    const openLocator = trimmed.match(/"locator"\s*:\s*"((?:[^"\\]|\\.)*)$/);
    const statusMatch = trimmed.match(/"http_status"\s*:\s*(\d+)/);
    const messageRaw = closedMessage?.[1] ?? openMessage?.[1];
    if (!messageRaw) return null;
    payload = { error: true, message: messageRaw.replace(/\\"/g, '"') };
    const locatorRaw = closedLocator?.[1] ?? openLocator?.[1];
    if (locatorRaw) payload.locator = locatorRaw.replace(/\\"/g, '"');
    const statusRaw = statusMatch?.[1];
    if (statusRaw) payload.http_status = Number(statusRaw);
  }
  if (payload?.error !== true) return null;
  const message = typeof payload.message === "string" ? payload.message : "";
  if (!message) return null;
  const locator =
    typeof payload.locator === "string"
      ? payload.locator
      : (() => {
          // Some tools nest the locator inside the message blob; pull
          // it back out so the chip header can render a host token.
          const m = message.match(/['"]([a-z]+:\/\/[^'"\s)]+)['"]/i);
          return m ? m[1] : undefined;
        })();
  const http_status = typeof payload.http_status === "number" ? payload.http_status : undefined;
  let locator_host: string | undefined;
  if (locator) {
    try {
      locator_host = new URL(locator).host;
    } catch {
      // Non-URL locators (filesystem paths, kaos:// uris): use the
      // first segment after the scheme as the locator token.
      const m = locator.match(/^([a-z]+):\/\/([^/]+)/i);
      locator_host = m ? m[2] : locator.slice(0, 32);
    }
  }
  let reason: string | undefined;
  if (http_status) {
    if (http_status === 404) reason = "404 Not Found";
    else if (http_status >= 500) reason = `${http_status} server error`;
    else if (http_status >= 400) reason = `${http_status} blocked`;
    else reason = `HTTP ${http_status}`;
  } else if (/retryable status/i.test(message)) {
    reason = "retryable HTTP";
  } else if (/not found/i.test(message)) {
    reason = "not found";
  } else if (/must use http or https/i.test(message)) {
    reason = "unsupported scheme";
  } else if (/timeout|timed out/i.test(message)) {
    reason = "timeout";
  } else if (/validation error/i.test(message)) {
    reason = "validation error";
  }
  return { message, locator, http_status, locator_host, reason };
}

export function formatToolCall(call: ToolCallSummary): FormattedToolCall {
  // Error envelope short-circuit: when the tool returned an
  // ``{"error": true, ...}`` payload, skip the per-tool formatter
  // (which would otherwise dump the raw JSON into the chip header)
  // and synthesise a clean "FAILED · <host> · <reason>" summary.
  const errorEnvelope = extractErrorEnvelope(call.result_preview);
  if (errorEnvelope) {
    const headerBits = ["FAILED"];
    if (errorEnvelope.locator_host) headerBits.push(errorEnvelope.locator_host);
    if (errorEnvelope.reason) headerBits.push(errorEnvelope.reason);
    return {
      label: toolLabel(call.name),
      args_summary: formatArgsPreview(call.args_preview),
      result_summary: headerBits.join(" · "),
      result_records: [],
      result_kind: "unknown",
      result_lead: "",
      result_raw_json: call.result_preview,
      is_error_envelope: true,
      error: errorEnvelope,
    };
  }

  const { lead, raw } = splitResultPreview(call.result_preview);
  let kind: ResultKind = "unknown";
  let inner: { args: string; summary: string; records: Record<string, unknown>[] };

  switch (call.name) {
    case "kaos-source-fr-search":
      kind = "fr_search";
      inner = formatFrSearch(lead, raw);
      break;
    case "kaos-source-fr-get-content":
      kind = "fr_content";
      inner = formatFrContent(lead, raw);
      break;
    case "kaos-source-fr-get-document":
      kind = "fr_doc";
      inner = formatFrContent(lead, raw);
      break;
    case "kaos-source-ecfr-content":
    case "kaos-source-ecfr-search-structure":
      kind = "ecfr_section";
      inner = formatEcfrSection(lead, raw);
      break;
    case "kaos-source-fetch-url":
      kind = "fetch_url";
      inner = formatFetchUrl(lead, raw);
      break;
    case "kaos-content-parse-markdown":
    case "kaos-content-parse-html":
      kind = "markdown_parse";
      inner = formatGeneric(lead, raw);
      break;
    case "kaos-pdf-extract-parse":
    case "kaos-pdf-extract-tables":
      kind = "pdf_extract";
      inner = formatGeneric(lead, raw);
      break;
    default:
      inner = formatGeneric(lead, raw);
  }

  const fromArgs = formatArgsPreview(call.args_preview);
  // Args from JSON (preferred) > args derived from result (fallback).
  const args_summary = fromArgs || inner.args;

  return {
    label: toolLabel(call.name),
    args_summary,
    result_summary: inner.summary,
    result_records: inner.records,
    result_kind: kind,
    result_lead: lead,
    result_raw_json: raw,
  };
}
