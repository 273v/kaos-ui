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
  Loader2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { ToolCallSummary } from "../lib/chat-state.js";
import { copyToClipboard } from "../lib/copy-to-clipboard.js";
import { JsonView } from "./JsonView.js";
import { formatToolCall, repairAndParseJson, type FormattedToolCall } from "./tool-formatters.js";

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
  const title = (record.title as string | undefined) ?? "(untitled)";
  const docNumber = (record.document_number as string | undefined) ?? "";
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

function StructuredResultBody({
  presentation,
  wasTruncated,
}: {
  presentation: FormattedToolCall;
  wasTruncated: boolean;
}) {
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
        {wasTruncated && (
          <div className="text-[10px] text-muted-foreground italic">
            kaos-agents truncated the wire preview — additional records may
            exist but didn't make it to the SPA.
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
  // generic JSON case.
  return <JsonView value={result_records[0]} maxHeight={240} truncated={wasTruncated} />;
}

export function ToolCallBlock({ call, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [showRaw, setShowRaw] = useState(false);
  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  const presentation = formatToolCall(call);
  const { label, args_summary, result_summary } = presentation;
  // Was the wire JSON unparseable as a whole? If so the structured
  // view is showing a *partial* repair and we should annotate that.
  const wasTruncated =
    !!presentation.result_raw_json &&
    presentation.result_records.length > 0 &&
    (() => {
      try {
        JSON.parse(presentation.result_raw_json!);
        return false;
      } catch {
        return true;
      }
    })();

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
              {parsedArgs ? (
                <JsonView value={parsedArgs} maxHeight={160} />
              ) : (
                <pre className="font-mono bg-muted rounded px-2 py-1 whitespace-pre-wrap break-words text-[11px]">
                  {call.args_preview}
                </pre>
              )}
            </div>
          )}
          {!showRaw && presentation.result_records.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                result
              </div>
              <StructuredResultBody presentation={presentation} wasTruncated={wasTruncated} />
            </div>
          )}
          {!showRaw && presentation.result_records.length === 0 && presentation.result_lead && (
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
                  truncated the wire preview at ~200 chars and the remaining
                  fragment didn't contain a parseable record. Use{" "}
                  <span className="underline">show raw</span> for the bytes
                  that did arrive, or copy the call JSON.
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
