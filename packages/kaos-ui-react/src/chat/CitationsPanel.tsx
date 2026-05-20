/**
 * Right-side citations panel. Driven by `useCitations`, which fires
 * post-turn extraction against the backend (see hook for the
 * wire-truncation rationale). Open/close + mounting strategy is
 * owned by the host — this component is presentational.
 *
 * Grouping (#310 polish): toggleable between "by kind" (default,
 * one section per citation kind across all messages) and "by
 * message" (one section per assistant turn showing only that
 * turn's citations).
 */

import { ExternalLink, Hash, Loader2, MessageSquare, Quote, X } from "lucide-react";
import { useState } from "react";

import type { Citation } from "../lib/citations.js";
import { EmptyState } from "./EmptyState.js";

interface Props {
  open: boolean;
  onClose: () => void;
  byMessage: Map<string, Citation[]>;
  pending: boolean;
  error: string | null;
  /** Kinds to hide from the panel (defaults to back-reference kinds). */
  hiddenKinds?: ReadonlySet<string>;
}

const DEFAULT_HIDDEN: ReadonlySet<string> = new Set(["id", "supra", "infra"]);

type GroupMode = "kind" | "message";

function groupByKind(
  byMessage: Map<string, Citation[]>,
  hidden: ReadonlySet<string>,
): Map<string, Citation[]> {
  const grouped = new Map<string, Citation[]>();
  for (const cites of byMessage.values()) {
    for (const c of cites) {
      if (hidden.has(c.kind)) continue;
      const list = grouped.get(c.kind) ?? [];
      list.push(c);
      grouped.set(c.kind, list);
    }
  }
  return grouped;
}

function filterByMessage(
  byMessage: Map<string, Citation[]>,
  hidden: ReadonlySet<string>,
): Map<string, Citation[]> {
  const out = new Map<string, Citation[]>();
  for (const [msgId, cites] of byMessage) {
    const visible = cites.filter((c) => !hidden.has(c.kind));
    if (visible.length) out.set(msgId, visible);
  }
  return out;
}

function prettyKind(kind: string): string {
  // `cfr` → `CFR`, `case` → `Case`, `sec_filing` → `SEC filing`.
  if (kind === kind.toLowerCase() && kind.length <= 4) return kind.toUpperCase();
  return kind
    .split("_")
    .map((part, i) => (i === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part.toLowerCase()))
    .join(" ");
}

// Coarse category coloring for kind badges. Maps each citation kind
// to one of five visual buckets so the user can scan a mixed-kind
// list and see the dominant domain at a glance.
function kindCategory(
  kind: string,
): "legal" | "finance" | "accounting" | "identifier" | "other" {
  const FINANCE = new Set([
    "sec_filing",
    "sec_release",
    "sec_staff_guidance",
    "finra",
    "exchange_rule",
    "banking",
    "basel",
    "cftc",
    "naic",
    "ffiec",
  ]);
  const ACCOUNTING = new Set([
    "fasb_asc",
    "fasb_asu",
    "fasb_legacy",
    "pcaob",
    "aicpa",
    "ifrs",
    "iaasb",
    "gasb",
    "fasab",
    "sasb",
    "tcfd",
    "issb",
    "gri",
  ]);
  const IDENTIFIER = new Set(["doi", "pubmed", "arxiv"]);
  if (FINANCE.has(kind)) return "finance";
  if (ACCOUNTING.has(kind)) return "accounting";
  if (IDENTIFIER.has(kind)) return "identifier";
  // Default everything else (case, cfr, usc, federal_register, constitution,
  // rules of evidence/civil_procedure, irs, executive_order, etc.) to legal.
  return "legal";
}

function KindBadge({ kind }: { kind: string }) {
  const category = kindCategory(kind);
  const palette: Record<string, string> = {
    legal: "bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/30",
    finance: "bg-green-500/10 text-green-700 dark:text-green-300 border-green-500/30",
    accounting: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30",
    identifier: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300 border-zinc-500/30",
    other: "bg-muted text-foreground/80 border-border",
  };
  return (
    <span
      className={`inline-block rounded-sm border px-1 py-0.5 text-[9px] uppercase tracking-wide ${palette[category]}`}
      title={`kind: ${kind} (${category})`}
    >
      {prettyKind(kind)}
    </span>
  );
}

function CitationCard({ c, showKindBadge }: { c: Citation; showKindBadge: boolean }) {
  const headline = c.normalized || c.raw;
  return (
    <li className="rounded-md border border-border bg-background px-2.5 py-1.5">
      {showKindBadge && (
        <div className="mb-1">
          <KindBadge kind={c.kind} />
        </div>
      )}
      {c.source_uri ? (
        <a
          href={c.source_uri}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium break-words inline-flex items-baseline gap-1 text-foreground hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
        >
          <span>{headline}</span>
          <ExternalLink
            aria-hidden="true"
            className="h-3 w-3 shrink-0 translate-y-px text-muted-foreground"
          />
        </a>
      ) : (
        <p className="text-xs font-medium break-words">{headline}</p>
      )}
      {c.normalized && c.normalized !== c.raw && (
        <p className="text-[11px] text-muted-foreground italic mt-0.5 break-words">"{c.raw}"</p>
      )}
      {c.pin_cite && <p className="text-[11px] text-muted-foreground mt-0.5">at {c.pin_cite}</p>}
    </li>
  );
}

export function CitationsPanel({
  open,
  onClose,
  byMessage,
  pending,
  error,
  hiddenKinds = DEFAULT_HIDDEN,
}: Props) {
  // Keep grouping mode hook-stable regardless of `open` so toggle
  // state survives panel close/reopen within the same session.
  const [groupMode, setGroupMode] = useState<GroupMode>("kind");

  if (!open) return null;

  const kindGroups = groupByKind(byMessage, hiddenKinds);
  const messageGroups = filterByMessage(byMessage, hiddenKinds);
  const visibleTotal = Array.from(kindGroups.values()).reduce((acc, arr) => acc + arr.length, 0);
  const kindKeys = Array.from(kindGroups.keys()).sort();
  const messageKeys = Array.from(messageGroups.keys());

  return (
    <aside
      className="w-80 flex-shrink-0 border-l border-border bg-card flex flex-col h-full"
      aria-label="Citations panel"
    >
      <header className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Quote className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Citations</span>
          <span className="text-xs text-muted-foreground tabular-nums">{visibleTotal}</span>
          {pending && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex items-center gap-1">
          {/* Grouping toggle (#310 polish). Two-button segmented control;
              compact enough not to crowd the header at 320px. */}
          <div className="inline-flex rounded-md border border-border bg-background overflow-hidden">
            <button
              type="button"
              onClick={() => setGroupMode("kind")}
              aria-pressed={groupMode === "kind"}
              title="Group by citation kind"
              aria-label="Group by kind"
              className={`px-1.5 py-1 text-[10px] uppercase tracking-wide ${
                groupMode === "kind"
                  ? "bg-accent/15 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Hash className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={() => setGroupMode("message")}
              aria-pressed={groupMode === "message"}
              title="Group by source message"
              aria-label="Group by message"
              className={`px-1.5 py-1 text-[10px] uppercase tracking-wide border-l border-border ${
                groupMode === "message"
                  ? "bg-accent/15 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <MessageSquare className="h-3 w-3" />
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground ml-1"
            aria-label="Close citations panel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="mx-3 mt-3 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive"
        >
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {visibleTotal === 0 && !pending && (
          <EmptyState
            icon={<Quote className="h-6 w-6" />}
            title="No citations yet"
            description="Citations appear here after the agent's response is extracted."
          />
        )}
        {groupMode === "kind" &&
          kindKeys.map((kind) => (
            <section key={kind} className="mb-4">
              <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                <KindBadge kind={kind} />
                <span className="tabular-nums">({kindGroups.get(kind)?.length ?? 0})</span>
              </h3>
              <ul className="space-y-2">
                {(kindGroups.get(kind) ?? []).map((c) => (
                  <CitationCard key={c.cite_id} c={c} showKindBadge={false} />
                ))}
              </ul>
            </section>
          ))}
        {groupMode === "message" &&
          messageKeys.map((msgId, idx) => {
            const cites = messageGroups.get(msgId) ?? [];
            return (
              <section key={msgId} className="mb-4">
                <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                  <MessageSquare className="h-3 w-3" />
                  <span>Turn {idx + 1}</span>
                  <span className="tabular-nums">({cites.length})</span>
                </h3>
                <ul className="space-y-2">
                  {cites.map((c) => (
                    <CitationCard key={c.cite_id} c={c} showKindBadge={true} />
                  ))}
                </ul>
              </section>
            );
          })}
      </div>
    </aside>
  );
}
