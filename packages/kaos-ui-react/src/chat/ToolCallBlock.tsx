/**
 * Inline tool-call card rendered under an assistant `<Message>`.
 *
 * Visibility model (VIS-4 redesign + VIS-4b structured-JSON pass):
 * - Collapsed row: status icon · friendly tool label · args summary
 *   · arrow · result summary. One scannable line per call, no raw
 *   JSON in the chip header.
 * - Expanded body: per-tool structured view when the result parses
 *   into a known shape (fr_search → cards, fr_doc → metadata card,
 *   fetch_url → link card). For unknown / partially-parsed payloads
 *   we render the JSON tree with `<JsonView>` (syntax-highlighted,
 *   indented, with a "kaos-agents truncated this" annotation when
 *   the wire preview was cut short).
 * - A "show raw" toggle exposes the original wire bytes for
 *   debugging; "copy json" puts the full `ToolCallSummary` on the
 *   clipboard via a robust helper (navigator.clipboard + execCommand
 *   fallback so users in non-focused or insecure contexts still get
 *   it).
 */

import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  FileCode,
  File as FileIcon,
  FileJson,
  FileText,
  Image as ImageIcon,
  Loader2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { ToolCallSummary } from "../lib/chat-state.js";
import { copyToClipboard } from "../lib/copy-to-clipboard.js";
import { JsonView } from "./JsonView.js";
import { type FormattedToolCall, formatToolCall, repairAndParseJson } from "./tool-formatters.js";

interface Props {
  call: ToolCallSummary;
  /** Start expanded. Default false. */
  defaultOpen?: boolean;
  /**
   * Group-level override (#507): when set, the card MIRRORS this
   * value and ignores its internal toggle. The parent `<ToolCallTimeline>`
   * uses this to drive expand-all / collapse-all in one click without
   * losing the per-card click handler when the override is cleared.
   * Default ``undefined`` — each card manages its own state from
   * ``defaultOpen``.
   */
  forceOpen?: boolean;
}

function StatusIcon({
  status,
  errorEnvelope,
}: {
  status: ToolCallSummary["status"];
  errorEnvelope?: boolean;
}) {
  if (status === "running") {
    return <Loader2 className="h-3.5 w-3.5 mt-0.5 shrink-0 animate-spin text-muted-foreground" />;
  }
  // Treat ``{"error": true, ...}`` payloads as errors even though the
  // wire ``status`` is ``"done"`` — the tool returned a failure, not
  // a successful result.
  if (status === "error" || errorEnvelope) {
    return <X className="h-3.5 w-3.5 mt-0.5 shrink-0 text-destructive" />;
  }
  return <Check className="h-3.5 w-3.5 mt-0.5 shrink-0 text-foreground" />;
}

type CopyState = "idle" | "copied" | "failed";

/**
 * Compact copy-to-clipboard button. Uses the robust copyToClipboard
 * helper (navigator.clipboard + execCommand fallback) so the button
 * never silently no-ops in non-focused / insecure / iframe contexts.
 */
function CopyJsonButton({ payload }: { payload: unknown }) {
  const [state, setState] = useState<CopyState>("idle");
  return (
    <button
      type="button"
      onClick={async (e) => {
        e.stopPropagation();
        const text = JSON.stringify(payload, null, 2);
        const ok = await copyToClipboard(text);
        setState(ok ? "copied" : "failed");
        setTimeout(() => setState("idle"), 2000);
      }}
      className={`inline-flex items-center gap-1 text-[10px] uppercase tracking-wider hover:text-foreground ${
        state === "failed" ? "text-destructive" : "text-muted-foreground"
      }`}
      title="Copy raw call JSON"
      aria-label={
        state === "copied"
          ? "Copied to clipboard"
          : state === "failed"
            ? "Copy failed — your browser blocked clipboard write"
            : "Copy raw call JSON"
      }
    >
      <Copy className="h-3 w-3" />
      {state === "copied" ? "copied" : state === "failed" ? "copy failed" : "copy json"}
    </button>
  );
}

function FrSearchResultCard({ record }: { record: Record<string, unknown> }) {
  const rawTitle = (record.title as string | undefined) ?? "";
  const docNumber = (record.document_number as string | undefined) ?? "";
  // When the wire preview was truncated mid-title, the repair drops
  // the broken value and we end up with `title = ""`. Showing
  // "(untitled)" is misleading — the document HAS a title, we just
  // couldn't reconstruct it. Use the document_number (or a short
  // placeholder) instead so the card reads honestly.
  const title = rawTitle || (docNumber ? `FR ${docNumber}` : "Title truncated in wire preview");
  const type = (record.type as string | undefined) ?? "";
  const date = (record.publication_date as string | undefined) ?? "";
  const htmlUrl = (record.html_url as string | undefined) ?? "";
  const agencies = Array.isArray(record.agencies)
    ? (record.agencies as Array<{ name?: string }>)
        .map((a) => a.name)
        .filter(Boolean)
        .join(", ")
    : "";
  return (
    <div className="rounded border border-border/60 bg-background px-2 py-1.5 text-xs">
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium flex-1 min-w-0 leading-snug">{title}</span>
        {htmlUrl && (
          <a
            href={htmlUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
            onClick={(e) => e.stopPropagation()}
          >
            open <ExternalLink className="h-2.5 w-2.5" />
          </a>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
        {docNumber && <span className="font-mono">{docNumber}</span>}
        {type && <span>· {type}</span>}
        {date && <span>· {date}</span>}
        {agencies && <span className="truncate">· {agencies}</span>}
      </div>
    </div>
  );
}

function FrDocCard({ record }: { record: Record<string, unknown> }) {
  const title = (record.title as string | undefined) ?? "";
  const docNumber = (record.document_number as string | undefined) ?? "";
  const citation = (record.citation as string | undefined) ?? "";
  const action = (record.action as string | undefined) ?? "";
  const effectiveOn = (record.effective_on as string | undefined) ?? "";
  const htmlUrl = (record.html_url as string | undefined) ?? "";
  return (
    <div className="rounded border border-border/60 bg-background px-2 py-1.5 text-xs space-y-0.5">
      {title && <div className="font-medium leading-snug">{title}</div>}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
        {docNumber && <span className="font-mono">{docNumber}</span>}
        {citation && <span>· {citation}</span>}
        {action && <span>· {action}</span>}
        {effectiveOn && <span>· effective {effectiveOn}</span>}
      </div>
      {htmlUrl && (
        <a
          href={htmlUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          open on federalregister.gov <ExternalLink className="h-2.5 w-2.5" />
        </a>
      )}
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function pickArtifactIcon(mime: string | undefined) {
  if (!mime) return FileIcon;
  if (mime.startsWith("image/")) return ImageIcon;
  if (mime === "application/json" || mime === "application/x-ndjson") return FileJson;
  if (mime === "application/xml" || mime === "text/html") return FileCode;
  if (mime.startsWith("text/")) return FileText;
  return FileIcon;
}

/**
 * Artifact card — rendered when a tool's structured_content carries an
 * ``artifact_id`` (Stage A+B of the no-hardcoded-caps-and-artifact-first-
 * tool-results plan). Replaces the previous behavior where artifact-
 * returning tools (Federal Register get-content, eCFR content, web
 * crawl, fetch-url) showed a truncated text snippet.
 *
 * Rendering priority:
 * 1. Manifest name + size + MIME chip (always shown).
 * 2. Originating ``source_uri`` (e.g. ``https://www.federalregister.gov/...``)
 *    as a clickable "view source" link when present — the user can
 *    cross-check against the upstream document.
 * 3. ``artifact_id`` in monospace + copy-to-clipboard for power users.
 * 4. ``body_uri`` (the ``kaos://artifacts/{id}/body`` resource) shown
 *    raw for power users who want to dereference via MCP
 *    ``resources/read``.
 */
function ArtifactCard({ record }: { record: Record<string, unknown> }) {
  const artifactId = (record.artifact_id as string | undefined) ?? "";
  const bodyUri = (record.body_uri as string | undefined) ?? "";
  const mimeType = (record.mime_type as string | undefined) ?? undefined;
  const size = (record.size as number | undefined) ?? 0;
  const sourceUri =
    (record.source_uri as string | undefined) ?? (record.source_url as string | undefined) ?? "";
  // Best-effort name: name → title → derive from source uri → artifact id tail
  const name =
    (record.name as string | undefined) ??
    (record.title as string | undefined) ??
    (sourceUri ? (sourceUri.split("/").filter(Boolean).pop() ?? "") : "") ??
    artifactId.slice(0, 8);
  const Icon = pickArtifactIcon(mimeType);
  const [copied, setCopied] = useState(false);

  return (
    <div className="rounded-md border border-border bg-background px-3 py-2 text-xs">
      <div className="flex items-start gap-2">
        <Icon className="h-5 w-5 mt-0.5 shrink-0 text-muted-foreground" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-[13px] leading-snug break-words">{name}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
            {mimeType && (
              <span className="inline-flex items-center rounded-sm bg-muted px-1 py-0.5 font-mono">
                {mimeType}
              </span>
            )}
            {size > 0 && <span>· {formatBytes(size)}</span>}
            <span className="font-mono">· artifact</span>
          </div>
          {sourceUri && (
            <a
              href={sourceUri}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground break-all"
              onClick={(e) => e.stopPropagation()}
              title="Open the originating source in a new tab"
            >
              <ExternalLink className="h-3 w-3 shrink-0" />
              <span>{sourceUri}</span>
            </a>
          )}
          {artifactId && (
            <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground/80">
              <span className="font-mono break-all">{artifactId}</span>
              <button
                type="button"
                onClick={async (e) => {
                  e.stopPropagation();
                  const ok = await copyToClipboard(bodyUri || artifactId);
                  setCopied(ok);
                  setTimeout(() => setCopied(false), 1500);
                }}
                className="uppercase tracking-wider hover:text-foreground inline-flex items-center gap-1"
                title="Copy kaos:// body URI"
              >
                <Copy className="h-2.5 w-2.5" />
                {copied ? "copied" : "copy uri"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Heuristic: does the record carry the artifact-first contract that
 * the kaos-core artifact tier system (Stage A, 0.1.0a8) emits? When
 * present, every other rendering path is overridden — the artifact is
 * the canonical answer.
 */
function isArtifactRecord(record: Record<string, unknown> | undefined): boolean {
  if (!record) return false;
  const id = record.artifact_id;
  return typeof id === "string" && id.length > 0;
}

function FetchUrlCard({ record }: { record: Record<string, unknown> }) {
  const url = (record.url as string | undefined) ?? "";
  return url ? (
    <div className="rounded border border-border/60 bg-background px-2 py-1.5 text-xs">
      <a
        href={url}
        target="_blank"
        rel="noreferrer noopener"
        className="font-mono text-[11px] break-all hover:text-foreground text-muted-foreground inline-flex items-start gap-1"
        onClick={(e) => e.stopPropagation()}
      >
        <ExternalLink className="h-3 w-3 mt-0.5 shrink-0" />
        <span>{url}</span>
      </a>
    </div>
  ) : null;
}

/**
 * Parse the tool's own "Found N documents" lead-in to figure out
 * how many records the agent actually saw, vs the count the SPA was
 * able to reconstruct from the wire preview. When the agent saw
 * more than we recovered, we tell the user that's a *display* gap
 * (kaos-agents wire cap), not a *search* gap.
 */
function extractFoundCount(lead: string): number | null {
  const m = lead.match(/Found\s+(\d+)/i);
  if (!m) return null;
  const n = Number.parseInt(m[1] ?? "", 10);
  return Number.isFinite(n) ? n : null;
}

function StructuredResultBody({
  presentation,
}: {
  presentation: FormattedToolCall;
}) {
  const { result_kind, result_records, result_lead } = presentation;
  if (result_records.length === 0) return null;
  // Stage C (no-hardcoded-caps-and-artifact-first-tool-results plan):
  // when the tool's structured_content carries an artifact_id, the
  // artifact is the canonical answer — render the file card instead
  // of whatever tool-specific shape would otherwise apply. Works for
  // every artifact-emitting tool: kaos-source-fr-get-content (B2),
  // kaos-source-ecfr-content (B2), kaos-source-fetch-url, kaos-web
  // crawl + batch-fetch (B3), etc.
  const first = result_records[0];
  if (first && isArtifactRecord(first)) {
    return <ArtifactCard record={first} />;
  }
  if (result_kind === "fr_search") {
    const shown = Math.min(result_records.length, 6);
    const found = extractFoundCount(result_lead);
    // How many records the agent actually saw but we couldn't render
    // (because kaos-agents capped the wire preview at ~200 chars and
    // we could only reconstruct N of them).
    const missingFromDisplay =
      found != null && found > result_records.length ? found - result_records.length : 0;
    // True when the records we DID reconstruct are obviously partial
    // (e.g. only document_number survived the truncation). In that case
    // we should lead with the lead-text + counts and demote the
    // partial records to a footnote, because rendering 1 card that
    // says "FR 2026-02331" + nothing else is more misleading than
    // useful on its own.
    const firstRecord = result_records[0];
    const recordsAreSparse =
      result_records.length <= 1 &&
      firstRecord !== undefined &&
      !((firstRecord.title as string | undefined) ?? "");
    return (
      <div className="space-y-1.5">
        {result_lead && (
          <div className="rounded border border-border/60 bg-background px-2 py-1.5 text-xs leading-relaxed">
            {result_lead}
          </div>
        )}
        {!recordsAreSparse &&
          result_records
            .slice(0, 6)
            .map((r, i) => (
              <FrSearchResultCard key={`${i}-${(r.document_number as string) ?? i}`} record={r} />
            ))}
        {!recordsAreSparse && result_records.length > 6 && (
          <div className="text-[10px] text-muted-foreground italic">
            …and {result_records.length - 6} more recovered records below
          </div>
        )}
        {!recordsAreSparse && missingFromDisplay > 0 && (
          <div className="text-[10px] text-muted-foreground italic">
            Showing {shown} of {found} results — the agent saw all {found}, but kaos-agents caps the
            wire preview at ~200 chars so only the first {result_records.length} reconstructed here.
            The agent's answer still drew on the full set.
          </div>
        )}
        {recordsAreSparse && (
          <div className="text-[10px] text-muted-foreground italic">
            The wire preview was truncated mid-record at ~200 chars, so the per-document detail
            isn't reconstructable here. The agent's answer drew on the full result set above; use{" "}
            <span className="underline">show raw</span> to inspect the bytes that did arrive.
          </div>
        )}
      </div>
    );
  }
  if (result_kind === "fr_content" || result_kind === "fr_doc") {
    return <FrDocCard record={result_records[0] ?? {}} />;
  }
  if (result_kind === "fetch_url") {
    return <FetchUrlCard record={result_records[0] ?? {}} />;
  }
  // Unknown structured payload — render as JsonView. The presentation
  // has at least one record we recovered, so this is the partial /
  // generic JSON case. We mark `truncated` based on whether the raw
  // wire JSON would round-trip cleanly; if not, the JsonView is
  // showing a *repair* and the user should know.
  const rawRoundTrips = (() => {
    if (!presentation.result_raw_json) return true;
    try {
      JSON.parse(presentation.result_raw_json);
      return true;
    } catch {
      return false;
    }
  })();
  return <JsonView value={result_records[0]} maxHeight={240} truncated={!rawRoundTrips} />;
}

export function ToolCallBlock({ call, defaultOpen = false, forceOpen }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [showRaw, setShowRaw] = useState(false);
  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);
  // #507: group-level expand-all / collapse-all override. When the
  // parent timeline toggles its master state, propagate to every card
  // by re-running the effect on `forceOpen` change. Clearing `forceOpen`
  // (parent sets to `undefined`) returns control to the per-card click.
  useEffect(() => {
    if (forceOpen !== undefined) {
      setOpen(forceOpen);
    }
  }, [forceOpen]);

  const presentation = formatToolCall(call);
  const { label, args_summary, result_summary } = presentation;
  // Pretty-printed args from JSON, when parseable. Falls back to the
  // raw string in `<pre>` only when it isn't JSON.
  const parsedArgs = call.args_preview
    ? (() => {
        try {
          return JSON.parse(call.args_preview);
        } catch {
          return repairAndParseJson(call.args_preview);
        }
      })()
    : null;

  return (
    <div className="rounded-md border border-border bg-card overflow-hidden text-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full text-left px-3 py-2 flex items-start gap-2 hover:bg-muted/60"
        title={`Tool: ${call.name}`}
      >
        <span className="mt-0.5 text-muted-foreground">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </span>
        <StatusIcon status={call.status} errorEnvelope={presentation.is_error_envelope} />
        <span className="flex-1 min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="font-medium text-[13px]">{label}</span>
            {args_summary && (
              <span className="font-mono text-[10px] text-muted-foreground truncate max-w-[60ch]">
                {args_summary}
              </span>
            )}
          </span>
          {call.status === "running" ? (
            <span className="block mt-0.5 text-xs text-muted-foreground italic">running…</span>
          ) : result_summary ? (
            <span
              className={`block mt-0.5 text-xs leading-snug ${
                presentation.is_error_envelope ? "text-destructive" : "text-muted-foreground"
              }`}
            >
              → {result_summary}
            </span>
          ) : null}
        </span>
      </button>
      {open && (
        <div className="px-3 py-2 text-xs space-y-2 border-t border-border/70">
          {/*
            Stage C — when the wire delivered ``structured_content`` with
            an ``artifact_id`` the artifact IS the canonical answer.
            Render the file card immediately, ahead of every other
            tool-specific shape, so the user always sees the materialised
            artifact instead of an empty body when the wire's
            ``result_preview`` text was truncated.
          */}
          {call.structured_content && isArtifactRecord(call.structured_content) && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                artifact
              </div>
              <ArtifactCard record={call.structured_content} />
            </div>
          )}
          {call.args_preview && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                arguments
              </div>
              {parsedArgs ? (
                <JsonView value={parsedArgs} maxHeight={160} />
              ) : (
                <pre className="font-mono bg-muted rounded px-2 py-1 whitespace-pre-wrap break-words text-[11px]">
                  {call.args_preview}
                </pre>
              )}
            </div>
          )}
          {/*
            Error envelope: when the tool returned ``{"error": true,
            ...}`` render a dedicated error card with the message +
            locator instead of letting the JsonView dump the raw
            payload. The raw JSON is still one click away via "show
            raw".
          */}
          {!showRaw && presentation.is_error_envelope && presentation.error && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-destructive mb-1">
                error
              </div>
              <div className="rounded border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-xs leading-relaxed">
                <div className="text-foreground whitespace-pre-wrap break-words">
                  {presentation.error.message}
                </div>
                {(presentation.error.locator ||
                  presentation.error.http_status ||
                  presentation.error.reason) && (
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
                    {presentation.error.locator && (
                      <span className="font-mono break-all">{presentation.error.locator}</span>
                    )}
                    {presentation.error.http_status && (
                      <span>· HTTP {presentation.error.http_status}</span>
                    )}
                    {presentation.error.reason && !presentation.error.http_status && (
                      <span>· {presentation.error.reason}</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          {!showRaw &&
            !presentation.is_error_envelope &&
            presentation.result_records.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                  result
                </div>
                <StructuredResultBody presentation={presentation} />
              </div>
            )}
          {!showRaw &&
            !presentation.is_error_envelope &&
            presentation.result_records.length === 0 &&
            presentation.result_lead && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                  result
                </div>
                <div className="rounded border border-border/60 bg-background px-2 py-1.5 text-xs leading-relaxed">
                  {presentation.result_lead}
                </div>
                {presentation.result_raw_json && (
                  <p className="mt-1 text-[10px] text-muted-foreground italic">
                    The agent's tool returned a longer payload, but kaos-agents truncated the wire
                    preview at ~200 chars and the remaining fragment didn't contain a parseable
                    record. Use <span className="underline">show raw</span> for the bytes that did
                    arrive, or copy the call JSON.
                  </p>
                )}
              </div>
            )}
          {showRaw && call.result_preview && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                raw result (wire bytes, may be truncated)
              </div>
              <pre className="font-mono bg-muted rounded px-2 py-1 whitespace-pre-wrap break-words max-h-64 overflow-y-auto text-[11px]">
                {call.result_preview}
              </pre>
            </div>
          )}
          {call.status === "error" && !call.result_preview && (
            <div className="text-destructive italic">Tool call failed.</div>
          )}
          <div className="flex items-center gap-3 pt-1">
            {call.result_preview && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowRaw((v) => !v);
                }}
                className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
              >
                {showRaw
                  ? presentation.result_records.length > 0
                    ? "structured view"
                    : "hide raw"
                  : "show raw"}
              </button>
            )}
            <CopyJsonButton payload={call} />
            <span className="ml-auto font-mono text-[10px] text-muted-foreground/70">
              {call.id.slice(0, 18)}
              {call.id.length > 18 ? "…" : ""}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
