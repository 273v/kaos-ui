/**
 * Tiny token + USD chip — typically shown under a finalized assistant
 * message, with the values pulled from a `turn_summary` event.
 */

interface Props {
  tokens?: number | null;
  costUsd?: number | null;
}

export function UsageChip({ tokens, costUsd }: Props) {
  if (!tokens && !costUsd) return null;
  return (
    <p className="mt-2 text-[11px] text-muted-foreground tabular-nums">
      {typeof tokens === "number" && `${tokens.toLocaleString()} tok`}
      {typeof tokens === "number" && typeof costUsd === "number" && " · "}
      {typeof costUsd === "number" && `$${costUsd.toFixed(4)}`}
    </p>
  );
}
