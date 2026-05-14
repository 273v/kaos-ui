/**
 * Per-message stats chip shown under a finalized assistant message.
 * Renders whichever of {latency, tokens, cost, tool count} are populated.
 * Each cell is monospaced + spaced via a middot so the row reads as
 * a quick-glance status: `8.2s · 3,240 tok · $0.0084 · 3 tools`.
 */

import { Clock, Coins, Hash, Wrench } from "lucide-react";

interface Props {
  /** Wall-clock turn duration in ms. */
  latencyMs?: number | null;
  /** Total token count for the turn. */
  tokens?: number | null;
  /** Cost in USD for the turn. */
  costUsd?: number | null;
  /** Number of tool calls made during the turn. */
  toolCount?: number | null;
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60_000);
  const sec = Math.round((ms % 60_000) / 1000);
  return `${min}m${sec.toString().padStart(2, "0")}s`;
}

function formatTokens(n: number): string {
  if (n < 1000) return n.toString();
  return `${(n / 1000).toFixed(1)}k`;
}

function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function UsageChip({ latencyMs, tokens, costUsd, toolCount }: Props) {
  const cells: { key: string; icon: typeof Clock; text: string }[] = [];
  if (typeof latencyMs === "number") {
    cells.push({ key: "lat", icon: Clock, text: formatLatency(latencyMs) });
  }
  if (typeof tokens === "number") {
    cells.push({ key: "tok", icon: Hash, text: `${formatTokens(tokens)} tok` });
  }
  if (typeof costUsd === "number") {
    cells.push({ key: "usd", icon: Coins, text: formatCost(costUsd) });
  }
  if (typeof toolCount === "number" && toolCount > 0) {
    cells.push({
      key: "tools",
      icon: Wrench,
      text: `${toolCount} tool${toolCount === 1 ? "" : "s"}`,
    });
  }
  if (cells.length === 0) return null;
  return (
    <p className="mt-2 text-xs text-muted-foreground tabular-nums flex flex-wrap items-center gap-x-3 gap-y-1">
      {cells.map(({ key, icon: Icon, text }) => (
        <span key={key} className="inline-flex items-center gap-1">
          <Icon className="h-3 w-3 opacity-60" />
          {text}
        </span>
      ))}
    </p>
  );
}
