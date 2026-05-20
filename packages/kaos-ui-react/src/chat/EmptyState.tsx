/**
 * Shared empty-state component for panel surfaces.
 *
 * Closes #315 (C.2 — Empty + zero-state pass across pages). Provides
 * a single visual treatment for "nothing here yet" UI across the
 * documents panel, citations panel, sessions list, transcript before
 * the first turn, run inspector before any events, etc.
 *
 * Composition: optional Lucide icon + headline + one-line body +
 * optional CTA button. All slots are independently optional so
 * callers can use any subset.
 *
 * Sizing: designed for narrow panels (256–320px) and main-column use.
 * Set `compact` for inline / dense surfaces (e.g. inside a card).
 */

import type { ReactNode } from "react";

interface Props {
  /** Lucide icon component (passed pre-styled), e.g. ``<FileText className="h-4 w-4" />``. */
  icon?: ReactNode;
  /** Short headline. */
  title?: string;
  /** One-line explanation. */
  description?: ReactNode;
  /** Optional CTA — a button or link node, rendered below the description. */
  action?: ReactNode;
  /** Dense variant: smaller padding + tighter type ramp. */
  compact?: boolean;
}

export function EmptyState({ icon, title, description, action, compact = false }: Props) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex flex-col items-center text-center text-muted-foreground ${
        compact ? "py-4 px-2 gap-1.5" : "py-8 px-4 gap-2"
      }`}
    >
      {icon && <div className={compact ? "opacity-60" : "opacity-50 mb-1"}>{icon}</div>}
      {title && (
        <p className={`font-medium text-foreground ${compact ? "text-xs" : "text-sm"}`}>{title}</p>
      )}
      {description && (
        <p className={`max-w-[28ch] leading-relaxed ${compact ? "text-[11px]" : "text-xs"}`}>
          {description}
        </p>
      )}
      {action && <div className={compact ? "mt-1" : "mt-2"}>{action}</div>}
    </div>
  );
}
