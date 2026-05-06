/**
 * UsageChip — tiny muted line under a finalized assistant message
 * showing tokens + cost. Sourced from kaos-agents `usage_observed` /
 * `turn_complete` events.
 *
 * Hidden when no usage info has arrived (e.g. first turn before
 * `usage_observed` fires, or backends that don't emit it).
 */
interface UsageChipProps {
  tokens?: number;
  costUsd?: number;
}

function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.001) return `$${(usd * 1000).toFixed(2)}m`; // milli-dollars for sub-cent
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function UsageChip({ tokens, costUsd }: UsageChipProps) {
  if (tokens == null && costUsd == null) return null;
  const parts: string[] = [];
  if (tokens != null) parts.push(`${tokens.toLocaleString()} tok`);
  if (costUsd != null) parts.push(formatCost(costUsd));
  return <div className="text-[11px] text-muted-foreground/70">{parts.join(" · ")}</div>;
}
