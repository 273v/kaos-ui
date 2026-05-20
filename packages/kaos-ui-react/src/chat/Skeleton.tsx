/**
 * Shared loading-skeleton primitives.
 *
 * Closes #316 (C.3 — Loading + skeleton states). Two primitives:
 *
 * - ``<SkeletonLine>`` — one shimmering rounded rectangle. Width
 *   defaults to ``w-full``; pass a `widthClass` prop to vary.
 * - ``<SkeletonRow>`` — a horizontally-arranged stack of skeleton
 *   lines + an optional leading shape, intended for list rows
 *   (sessions list, documents, citations). Renders N skeleton rows
 *   when `count` is set.
 *
 * Both honour `prefers-reduced-motion` by dropping the pulse
 * animation. They use Tailwind's ``animate-pulse`` so no extra CSS
 * is needed; consumers that want different timing can override the
 * class via `className`.
 */

interface LineProps {
  /** Tailwind width class, e.g. ``w-1/2``, ``w-24``. */
  widthClass?: string;
  /** Tailwind height class, e.g. ``h-3``, ``h-4``. */
  heightClass?: string;
  /** Extra className appended to defaults. */
  className?: string;
}

export function SkeletonLine({
  widthClass = "w-full",
  heightClass = "h-3",
  className = "",
}: LineProps) {
  return (
    <div
      className={`rounded bg-muted/60 animate-pulse motion-reduce:animate-none ${heightClass} ${widthClass} ${className}`}
      aria-hidden="true"
    />
  );
}

interface RowProps {
  /** How many skeleton rows to render. Default 1. */
  count?: number;
  /** Show a leading square (avatar / icon placeholder). */
  leadingShape?: boolean;
  /** Number of text lines per row. Default 2. */
  lines?: number;
  /** Extra className on each row container. */
  className?: string;
}

export function SkeletonRow({
  count = 1,
  leadingShape = false,
  lines = 2,
  className = "",
}: RowProps) {
  const rows = Array.from({ length: Math.max(count, 0) });
  return (
    <div role="status" aria-live="polite" aria-label="Loading">
      {rows.map((_, rowIdx) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: skeleton rows are content-free.
          key={rowIdx}
          className={`flex items-start gap-2 py-2 ${className}`}
        >
          {leadingShape && (
            <div
              className="h-8 w-8 rounded-md bg-muted/60 animate-pulse motion-reduce:animate-none shrink-0"
              aria-hidden="true"
            />
          )}
          <div className="flex-1 space-y-1.5 min-w-0">
            {Array.from({ length: Math.max(lines, 1) }).map((__, lineIdx) => (
              <SkeletonLine
                // biome-ignore lint/suspicious/noArrayIndexKey: skeleton lines are content-free.
                key={lineIdx}
                widthClass={lineIdx === lines - 1 ? "w-2/3" : "w-full"}
              />
            ))}
          </div>
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}
