/**
 * `<DataTable>` — generic tabular primitive for `kaos-tabular`
 * summaries, document-comparison grids, citation tables, and any
 * other rectangular data the agent surfaces inside the chat.
 *
 * Design intent:
 *   - **Hairline borders, no zebra fills by default.** Inspired by
 *     Linear's issue grid + Stripe Dashboard — quiet on the eye,
 *     trusted-looking for legal/financial data.
 *   - **Three density tiers** (compact / default / comfortable) so
 *     the same component works as a sidebar mini-grid AND a
 *     full-width comparison view.
 *   - **Typed cells.** A `Column<T>` declares a `kind` —
 *     `text` / `number` / `currency` / `percent` / `date` / `code`
 *     / `badge` / `link` / `custom`. The component picks the
 *     right alignment + formatting + monospace pairing for each.
 *   - **Sticky header.** First row stays pinned during vertical
 *     scroll inside the container.
 *   - **Sortable.** Click a header cell to sort by that column.
 *     Sort state is local + uncontrolled; consumers who want to
 *     drive it externally can pass `sortBy` + `onSortChange`.
 *   - **Accessible.** Semantic `<table>` markup with
 *     `<caption>` / `<thead>` / `<tbody>`; `scope` on headers;
 *     `aria-sort` on the active sort column.
 *
 * Not in scope for v1:
 *   - Virtualization (rely on browser native; ~5k rows is the
 *     practical ceiling before this matters).
 *   - Row selection / bulk actions (build atop, not into).
 *   - Column resizing / drag-reorder (defer to v0.2).
 *
 * Used by:
 *   - `kaos-md`'s `<table>` renderer (auto-promotes plain markdown
 *     tables that have a header row).
 *   - Future "compare N documents" surfaces that call
 *     `kaos-tabular-summarize` on a doc set.
 */

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useMemo, useState } from "react";

/** Cell-type discriminator — drives alignment, formatting, font. */
export type ColumnKind =
  | "text"
  | "number"
  | "currency"
  | "percent"
  | "date"
  | "code"
  | "badge"
  | "link"
  | "custom";

export interface Column<Row> {
  /** Stable key — corresponds to the row property to read. */
  id: keyof Row & string;
  /** Human-visible header label. */
  label: string;
  /** Cell type — drives default formatter + alignment + font choice. */
  kind?: ColumnKind;
  /**
   * Custom width — `"auto"` (default), `"min"` (shrink-to-fit), or a
   * concrete value (`"160px"`, `"12ch"`, `"1fr"`). Implemented via
   * CSS `min-width` / `width` on the `<col>`.
   */
  width?: string;
  /** Right-aligned text override. Defaults true for number/currency/percent. */
  numeric?: boolean;
  /** Disable sorting on this column. Defaults to enabled. */
  sortable?: boolean;
  /**
   * Custom renderer for the cell value. Receives the row and the raw
   * value. Overrides the default `kind`-based formatter.
   */
  render?: (value: Row[keyof Row], row: Row) => React.ReactNode;
}

export type DataTableDensity = "compact" | "default" | "comfortable";

export interface DataTableProps<Row> {
  columns: Column<Row>[];
  rows: Row[];
  /** Optional caption — rendered as a `<caption>` for a11y + screen-reader context. */
  caption?: string;
  /** Row density. Defaults to `"default"`. */
  density?: DataTableDensity;
  /** Controlled sort state (id of the column). Omit for uncontrolled. */
  sortBy?: string;
  /** Controlled sort direction. */
  sortDirection?: "asc" | "desc";
  /** Called when the user clicks a sortable header. */
  onSortChange?: (id: string, direction: "asc" | "desc") => void;
  /** Sticky header (default true) — gated when the table is short. */
  stickyHeader?: boolean;
  /** Stable per-row key. Defaults to the row's `id` field if present, else the index. */
  rowKey?: (row: Row, index: number) => string | number;
  /** Class hook on the root element. */
  className?: string;
  /** Empty-state copy when `rows` is empty. */
  emptyMessage?: string;
}

// ── default formatters (Intl-based, no external deps) ────────────────

function fmtNumber(v: unknown): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(v);
}
function fmtCurrency(v: unknown): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "";
  // Conservative: no currency symbol unless the caller passes one
  // via a custom `render`. We just monospace-align with two decimals.
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v);
}
function fmtPercent(v: unknown): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "";
  // Heuristic: < 1 means "0.42 → 42%", >= 1 means "already in %".
  const scaled = Math.abs(v) <= 1 ? v * 100 : v;
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(scaled)}%`;
}
function fmtDate(v: unknown): string {
  if (v == null) return "";
  const d = v instanceof Date ? v : new Date(String(v));
  if (Number.isNaN(d.valueOf())) return String(v);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(d);
}

const DENSITY_ROW: Record<DataTableDensity, string> = {
  compact: "h-7 text-[12px]",
  default: "h-9 text-[13px]",
  comfortable: "h-11 text-[14px]",
};
const DENSITY_PAD: Record<DataTableDensity, string> = {
  compact: "px-2",
  default: "px-3",
  comfortable: "px-3.5",
};

function alignmentFor<R>(col: Column<R>): "left" | "right" {
  if (col.numeric != null) return col.numeric ? "right" : "left";
  if (col.kind === "number" || col.kind === "currency" || col.kind === "percent") {
    return "right";
  }
  return "left";
}

function defaultRenderer<R>(col: Column<R>, value: R[keyof R]): React.ReactNode {
  if (value == null || value === "") return <span className="text-foreground/30">—</span>;
  switch (col.kind) {
    case "number":
      return fmtNumber(value);
    case "currency":
      return fmtCurrency(value);
    case "percent":
      return fmtPercent(value);
    case "date":
      return fmtDate(value);
    case "code":
      return <code className="font-mono text-[12.5px] text-foreground/85">{String(value)}</code>;
    case "badge":
      return (
        <span className="inline-flex items-center rounded-full border border-border bg-muted/60 px-2 py-0.5 text-[11px] font-medium text-foreground/80">
          {String(value)}
        </span>
      );
    case "link":
      if (typeof value === "string" && /^https?:\/\//.test(value)) {
        return (
          <a
            href={value}
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground underline decoration-border underline-offset-2 hover:decoration-foreground"
          >
            {value}
          </a>
        );
      }
      return String(value);
    default:
      return String(value);
  }
}

// ── uncontrolled-or-controlled sort hook ─────────────────────────────

function useSort(
  controlledId: string | undefined,
  controlledDir: "asc" | "desc" | undefined,
  onChange: ((id: string, dir: "asc" | "desc") => void) | undefined,
) {
  const [localId, setLocalId] = useState<string | undefined>(undefined);
  const [localDir, setLocalDir] = useState<"asc" | "desc">("asc");

  const isControlled = onChange != null && controlledId !== undefined;
  const sortId = isControlled ? controlledId : localId;
  const sortDir = isControlled ? (controlledDir ?? "asc") : localDir;

  const cycle = (id: string) => {
    let nextDir: "asc" | "desc" = "asc";
    if (sortId === id) {
      nextDir = sortDir === "asc" ? "desc" : "asc";
    }
    if (isControlled) {
      onChange?.(id, nextDir);
    } else {
      setLocalId(id);
      setLocalDir(nextDir);
    }
  };

  return { sortId, sortDir, cycle };
}

// ── main component ───────────────────────────────────────────────────

export function DataTable<Row extends Record<string, unknown>>({
  columns,
  rows,
  caption,
  density = "default",
  sortBy,
  sortDirection,
  onSortChange,
  stickyHeader = true,
  rowKey,
  className,
  emptyMessage = "No rows",
}: DataTableProps<Row>) {
  const { sortId, sortDir, cycle } = useSort(sortBy, sortDirection, onSortChange);

  const sortedRows = useMemo(() => {
    if (!sortId) return rows;
    const col = columns.find((c) => c.id === sortId);
    if (!col) return rows;
    const cmp = (a: Row, b: Row): number => {
      const va = a[col.id];
      const vb = b[col.id];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      // Number-shaped types compare numerically; everything else
      // compares lexicographically via String() for stability.
      if (col.kind === "number" || col.kind === "currency" || col.kind === "percent") {
        return (va as number) - (vb as number);
      }
      if (col.kind === "date") {
        return new Date(va as string).valueOf() - new Date(vb as string).valueOf();
      }
      return String(va).localeCompare(String(vb));
    };
    const arr = [...rows].sort(cmp);
    return sortDir === "desc" ? arr.reverse() : arr;
  }, [rows, columns, sortId, sortDir]);

  const keyFor = (row: Row, idx: number): string | number => {
    if (rowKey) return rowKey(row, idx);
    if ("id" in row && (typeof row.id === "string" || typeof row.id === "number")) {
      return row.id as string | number;
    }
    return idx;
  };

  return (
    <div
      className={`w-full overflow-x-auto rounded-lg border border-border bg-card ${className ?? ""}`}
    >
      <table className="w-full border-collapse">
        {caption && (
          <caption className="px-3 py-2 text-left text-[12px] text-foreground/55 border-b border-border bg-muted/30">
            {caption}
          </caption>
        )}
        <colgroup>
          {columns.map((col) => (
            <col key={col.id} style={col.width ? { width: col.width } : undefined} />
          ))}
        </colgroup>
        <thead
          className={stickyHeader ? "sticky top-0 z-[1] bg-muted/40 backdrop-blur" : "bg-muted/40"}
        >
          <tr className={DENSITY_ROW[density]}>
            {columns.map((col) => {
              const isActive = sortId === col.id;
              const sortable = col.sortable !== false;
              const align = alignmentFor(col);
              return (
                <th
                  key={col.id}
                  scope="col"
                  aria-sort={
                    isActive
                      ? sortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : sortable
                        ? "none"
                        : undefined
                  }
                  className={[
                    DENSITY_PAD[density],
                    "border-b border-border text-foreground/70 font-medium uppercase tracking-[0.04em] text-[10px]",
                    align === "right" ? "text-right" : "text-left",
                  ].join(" ")}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => cycle(col.id)}
                      className={[
                        "inline-flex items-center gap-1 hover:text-foreground",
                        align === "right" ? "flex-row-reverse" : "",
                      ].join(" ")}
                      aria-label={`Sort by ${col.label}${
                        isActive
                          ? sortDir === "asc"
                            ? ", currently ascending"
                            : ", currently descending"
                          : ""
                      }`}
                    >
                      <span>{col.label}</span>
                      {isActive ? (
                        sortDir === "asc" ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowDown className="h-3 w-3" />
                        )
                      ) : (
                        <ArrowUpDown className="h-3 w-3 opacity-30" />
                      )}
                    </button>
                  ) : (
                    <span>{col.label}</span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="py-6 text-center text-[12px] italic text-foreground/55"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            sortedRows.map((row, idx) => (
              <tr
                key={keyFor(row, idx)}
                className={[
                  DENSITY_ROW[density],
                  "border-b border-border/60 last:border-b-0 hover:bg-muted/30 transition-colors",
                ].join(" ")}
              >
                {columns.map((col) => {
                  const value = row[col.id] as Row[keyof Row];
                  const align = alignmentFor(col);
                  const numericFont =
                    col.kind === "number" || col.kind === "currency" || col.kind === "percent";
                  return (
                    <td
                      key={col.id}
                      className={[
                        DENSITY_PAD[density],
                        "text-foreground/90 align-middle",
                        align === "right" ? "text-right" : "text-left",
                        numericFont ? "tabular-nums font-mono text-[12.5px]" : "",
                      ].join(" ")}
                    >
                      {col.render ? col.render(value, row) : defaultRenderer(col, value)}
                    </td>
                  );
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
