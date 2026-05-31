/**
 * Floating control cluster for the transcript scroll state machine.
 *
 * Two affordances rendered bottom-right of the transcript scroll
 * container:
 *
 *   1. "Jump to latest ↓" pill — visible only when `hasNewContent`
 *      is true (i.e. user has scrolled up OR locked, and new content
 *      has arrived since). Click jumps to bottom and resumes FOLLOW.
 *   2. Lock toggle (small icon button) — always visible. Pin icon
 *      when AUTO/PAUSED, filled amber pin when LOCKED. Tooltip
 *      describes the state.
 *
 * Visual language: matches the existing chrome (hairline border,
 * paper bg, amber accent, 6px radii, Inter). The pill uses a tiny
 * fade-in via `data-state` so the appearance is non-jarring; under
 * `prefers-reduced-motion` the fade is disabled by the CSS rule in
 * globals.css.
 *
 * Accessibility:
 *   - The pill is a `<button>` with an accessible name including
 *     the visible label.
 *   - The lock toggle uses `aria-pressed` to expose state to ATs.
 *   - Both controls are reachable in tab order; on focus they show
 *     a 1px ring (the existing kaos-ui ring color, not 2px).
 */

import { ArrowDown, Lock, LockOpen } from "lucide-react";
import type { AutoScrollMode } from "./use-auto-scroll.js";

interface Props {
  mode: AutoScrollMode;
  hasNewContent: boolean;
  onJumpToLatest(): void;
  onToggleLock(): void;
}

export function JumpToLatestPill({ mode, hasNewContent, onJumpToLatest, onToggleLock }: Props) {
  // The container is `position: absolute` inside the transcript
  // scroll container — it stays glued to the visible bottom-right
  // regardless of scroll position. pointer-events: none on the
  // container so it doesn't trap clicks on the underlying
  // transcript; the individual controls re-enable it.
  return (
    <div
      className="pointer-events-none absolute right-4 bottom-4 z-20 flex items-center gap-2"
      // The data-state lets the CSS rule in globals.css attach a
      // reduced-motion-aware fade-in for the pill specifically.
      data-state={hasNewContent ? "open" : "closed"}
    >
      {hasNewContent && (
        <button
          type="button"
          onClick={onJumpToLatest}
          // Pill chrome: paper bg, hairline border, amber accent dot,
          // 6px radius. Matches the existing user-card / chip palette.
          className={
            "pointer-events-auto inline-flex items-center gap-1.5 " +
            "rounded-full border border-[oklch(0.88_0.005_80)] " +
            "bg-[oklch(0.984_0.003_85)] px-3 py-1.5 " +
            "text-xs font-medium text-foreground " +
            "shadow-[0_2px_8px_oklch(0_0_0_/_0.08)] " +
            "hover:bg-[oklch(0.965_0.005_85)] " +
            "focus:outline-none focus-visible:ring-1 focus-visible:ring-[oklch(0.708_0.008_80)] " +
            "transition-colors"
          }
          aria-label="Jump to latest message"
          title="Jump to latest message (End)"
        >
          {/* Amber accent dot — same visual vocabulary as the
              assistant role marker, signals "new agent activity". */}
          <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-accent" />
          <span>Jump to latest</span>
          <ArrowDown className="h-3.5 w-3.5" />
        </button>
      )}

      <button
        type="button"
        onClick={onToggleLock}
        aria-pressed={mode === "locked"}
        aria-label={
          mode === "locked"
            ? "Unlock auto-scroll (currently locked at this position)"
            : "Lock scroll position"
        }
        title={
          mode === "locked"
            ? "Scroll locked at this position. Click to unlock + jump to latest."
            : "Lock the scroll position so new messages don't move the view."
        }
        className={`pointer-events-auto inline-flex h-8 w-8 items-center justify-center rounded-full border ${
          mode === "locked"
            ? "border-accent bg-accent text-accent-foreground shadow-[0_2px_6px_oklch(0_0_0_/_0.1)]"
            : "border-[oklch(0.88_0.005_80)] bg-[oklch(0.984_0.003_85)] text-foreground/70 hover:text-foreground hover:bg-[oklch(0.965_0.005_85)] shadow-[0_1px_3px_oklch(0_0_0_/_0.06)]"
        } focus:outline-none focus-visible:ring-1 focus-visible:ring-[oklch(0.708_0.008_80)] transition-colors`}
      >
        {mode === "locked" ? (
          <Lock className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <LockOpen className="h-3.5 w-3.5" aria-hidden />
        )}
      </button>
    </div>
  );
}
