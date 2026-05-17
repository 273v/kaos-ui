/**
 * Inline tool-call card rendered under an assistant `<Message>`.
 *
 * Visibility model (VIS-4 redesign):
 * - Collapsed row: status icon · friendly tool label · args summary
 *   · arrow · result summary. Designed so the user gets the WHO /
 *   WHAT / OUTCOME of every tool call in one line of dense, scannable
 *   typography — no raw JSON in the chip header.
 * - Expanded body: structured result view per tool family (search →
 *   list of document cards with title + doc# + date + link; fetch →
 *   doc preview card; etc.) for known tools. Unknown tools fall back
 *   to monospace blocks. A "raw" toggle exposes the wire JSON for
 *   debugging.
 * - `defaultOpen` keeps the in-flight assistant message / errored /
 *   running calls expanded by default, plus when the user has the
 *   verbose-tools toggle on.
 */

import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  Loader2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { ToolCallSummary } from "../lib/chat-state.js";
import { formatToolCall, type FormattedToolCall } from "./tool-formatters.js";

interface Props {
  call: ToolCallSummary;
  /** Start expanded. Default false. */
  defaultOpen?: boolean;
}

function StatusIcon({ status }: { status: ToolCallSummary["status"] }) {
  if (status === "running") {
    return <Loader2 className="h-3.5 w-3.5 mt-0.5 shrink-0 animate-spin text-muted-foreground" />;
  }
  if (status === "error") {
    return <X className="h-3.5 w-3.5 mt-0.5 shrink-0 text-destructive" />;
  }
  return <Check className="h-3.5 w-3.5 mt-0.5 shrink-0 text-foreground" />;
}

/**
 * Compact copy-to-clipboard button for the raw call JSON. Keeps the
 * "I want the unprocessed bytes" affordance one click away without
 * stealing chip header real estate.
 */
function CopyJsonButton({ payload }: { payload: unknown }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void navigator.clipboard
          .writeText(JSON.stringify(payload, null, 2))
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => {
            /* clipboard write can fail in secure contexts; ignore */
          });
      }}
      className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
      title="Copy raw call JSON"
    >
      <Copy className="h-3 w-3" />
      {copied ? "copied" : "copy json"}
    </button>
  );
}

/**
 * Render a single `kaos-source-fr-search` result as a compact citation
 * card. Used by the expanded body when the result_kind is `fr_search`.
 */
function FrSearchResultCard({ record }: { record: Record<string, unknown> }) {
  const title = (record.title as string | undefined) ?? "(untitled)";
  const docNumber = (record.document_number as string | undefined) ?? "";
  const type = (record.type as string | undefined) ?? "";
  const date = (record.publication_date as string | undefined) ?? "";
  const htmlUrl = (record.html_url as string | undefined) ?? "";
  const agencies = Array.isArray(record.agencies)
    ? (record.agencies as Array<{ name?: string }>).map((a) => a.name).filter(Boolean).join(", ")
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

/**
 * Render the single-doc payload from `fr-get-content` / `fr-get-document`.
 * The wire returns a rich object — surface the bits a legal reader
 * actually needs: title, citation, action type, dates, source link.
 */
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

function StructuredResultBody({ presentation }: { presentation: FormattedToolCall }) {
  const { result_kind, result_records } = presentation;
  if (result_records.length === 0) return null;
  if (result_kind === "fr_search") {
    return (
      <div className="space-y-1">
        {result_records.slice(0, 6).map((r, i) => (
          <FrSearchResultCard key={`${i}-${(r.document_number as string) ?? i}`} record={r} />
        ))}
        {result_records.length > 6 && (
          <div className="text-[10px] text-muted-foreground italic">
            …and {result_records.length - 6} more
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
  // Unknown structured payload — render as 2-column kv list.
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-2 gap-y-0.5 text-[11px]">
      {Object.entries(result_records[0] ?? {})
        .slice(0, 8)
        .map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground font-mono">{k}</dt>
            <dd className="truncate">
              {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </dd>
          </div>
        ))}
    </dl>
  );
}

export function ToolCallBlock({ call, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [showRaw, setShowRaw] = useState(false);
  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  const presentation = formatToolCall(call);
  const { label, args_summary, result_summary } = presentation;

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
        <StatusIcon status={call.status} />
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
            <span className="block mt-0.5 text-xs text-muted-foreground leading-snug">
              → {result_summary}
            </span>
          ) : null}
        </span>
      </button>
      {open && (
        <div className="px-3 py-2 text-xs space-y-2 border-t border-border/70">
          {call.args_preview && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                arguments
              </div>
              <pre className="font-mono bg-muted rounded px-2 py-1 whitespace-pre-wrap break-words text-[11px]">
                {call.args_preview}
              </pre>
            </div>
          )}
          {presentation.result_records.length > 0 && !showRaw && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                result
              </div>
              <StructuredResultBody presentation={presentation} />
            </div>
          )}
          {presentation.result_records.length === 0 && presentation.result_lead && !showRaw && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                result
              </div>
              <div className="rounded border border-border/60 bg-background px-2 py-1.5 text-xs leading-relaxed">
                {presentation.result_lead}
              </div>
              {presentation.result_raw_json && (
                <p className="mt-1 text-[10px] text-muted-foreground italic">
                  The agent's tool returned a longer payload, but kaos-agents
                  truncated the wire preview at ~200 chars. Use{" "}
                  <span className="underline">show raw</span> to inspect what
                  made it through, or copy the call JSON for the full reproducer.
                </p>
              )}
            </div>
          )}
          {showRaw && call.result_preview && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                raw result (truncated by agent)
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
