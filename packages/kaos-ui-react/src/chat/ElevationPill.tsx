/**
 * Auto-elevation pill (kaos-agents 0.1.0a4 AgenticLoop).
 *
 * Renders above an assistant message when the loop applied at least one
 * silent (green-auto) elevation during this turn. Shows the most recent
 * elevation chip-by-chip with an inline "Pin to session" affordance —
 * the host wires the click to `PATCH /v1/chat/sessions/{id}/tool-set`.
 *
 * Renders nothing when no elevations happened. Multiple iterations
 * collapse to one pill listing every distinct group added.
 */

import { Sparkles } from "lucide-react";

import type { ElevationSnapshot } from "../lib/chat-state.js";

interface Props {
  /** Per-iteration elevation snapshots, in order. */
  elevations?: ElevationSnapshot[];
  /**
   * Called when the user clicks "Pin to session". The host should
   * PATCH the session's tool-set to permanently include `groups` in
   * `allowed_groups`. Optional — without it the pill is read-only.
   */
  onPinToSession?(groups: string[]): void;
}

export function ElevationPill({ elevations, onPinToSession }: Props) {
  if (!elevations || elevations.length === 0) return null;

  // Collapse across iterations — the user only cares about WHICH groups
  // were added, not the per-iteration breakdown.
  const allGroups = Array.from(
    new Set(elevations.flatMap((e) => e.elevated_groups)),
  ).sort();

  if (allGroups.length === 0) return null;
  // Latest rationale wins (most recent iteration explains why we ended here).
  const latestRationale = elevations[elevations.length - 1]?.rationale ?? "";

  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-1.5 rounded-md border border-accent/40 bg-accent/5 px-2 py-1 text-xs"
      title={latestRationale}
    >
      <Sparkles className="h-3 w-3 text-accent" />
      <span className="font-medium text-foreground">Auto-enabled:</span>
      <span className="text-foreground">{allGroups.join(", ")}</span>
      {onPinToSession && (
        <button
          type="button"
          onClick={() => onPinToSession(allGroups)}
          className="ml-1 rounded border border-accent/50 px-1.5 py-0.5 text-[10px] font-medium text-accent transition-colors hover:bg-accent/10"
        >
          Pin to session
        </button>
      )}
    </div>
  );
}
