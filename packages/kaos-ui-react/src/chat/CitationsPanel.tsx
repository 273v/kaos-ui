/**
 * Right-side citations panel. Driven by `useCitations`, which fires
 * post-turn extraction against the backend (see hook for the
 * wire-truncation rationale). Open/close + mounting strategy is
 * owned by the host — this component is presentational.
 */

import { ExternalLink, Loader2, Quote, X } from "lucide-react";

import type { Citation } from "../lib/citations.js";

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

function prettyKind(kind: string): string {
  // `cfr` → `CFR`, `case` → `Case`, `sec_filing` → `SEC filing`.
  if (kind === kind.toLowerCase() && kind.length <= 4) return kind.toUpperCase();
  return kind
    .split("_")
    .map((part, i) => (i === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part.toLowerCase()))
    .join(" ");
}

export function CitationsPanel({
  open,
  onClose,
  byMessage,
  pending,
  error,
  hiddenKinds = DEFAULT_HIDDEN,
}: Props) {
  if (!open) return null;
  const groups = groupByKind(byMessage, hiddenKinds);
  const kinds = Array.from(groups.keys()).sort();
  const visibleTotal = Array.from(groups.values()).reduce((acc, arr) => acc + arr.length, 0);

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
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Close citations panel"
        >
          <X className="h-4 w-4" />
        </button>
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
          <p className="text-xs text-muted-foreground italic">
            No citations detected yet. Citations appear here after the agent's response is
            extracted.
          </p>
        )}
        {kinds.map((kind) => (
          <section key={kind} className="mb-4">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              {prettyKind(kind)}
              <span className="ml-1 tabular-nums">({groups.get(kind)?.length ?? 0})</span>
            </h3>
            <ul className="space-y-2">
              {(groups.get(kind) ?? []).map((c) => {
                const headline = c.normalized || c.raw;
                return (
                  <li
                    key={c.cite_id}
                    className="rounded-md border border-border bg-background px-2.5 py-1.5"
                  >
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
                      <p className="text-[11px] text-muted-foreground italic mt-0.5 break-words">
                        "{c.raw}"
                      </p>
                    )}
                    {c.pin_cite && (
                      <p className="text-[11px] text-muted-foreground mt-0.5">at {c.pin_cite}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  );
}
