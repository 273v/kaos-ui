/**
 * Live cost + token roll-up strip. Drops into a header / sidebar /
 * anywhere a "where is this session's spend going?" indicator is
 * useful.
 *
 * Feed it the raw event list (typically `useSendMessage().rawEvents`)
 * — internally it runs `useCostAggregation` to derive per-model rows.
 */

import { DollarSign, Hash } from "lucide-react";

import { useCostAggregation } from "../hooks/use-cost-aggregation.js";
import type { KaosAgentEvent } from "../lib/events.js";

export interface CostStripProps {
  events: ReadonlyArray<KaosAgentEvent | { event: KaosAgentEvent }>;
  /** Show per-model breakdown rows under the total. Defaults to true. */
  perModel?: boolean;
  /** Optional className appended to the root container. */
  className?: string;
}

function formatCost(usd: number): string {
  if (usd < 0.0001 && usd > 0) return "<$0.0001";
  return `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

function formatTokens(n: number): string {
  if (n < 1000) return n.toString();
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function CostStrip({ events, perModel = true, className }: CostStripProps) {
  const { byModel, total } = useCostAggregation(events);

  if (total.calls === 0) {
    return (
      <div
        className={`text-xs text-muted-foreground italic px-3 py-1.5 ${className ?? ""}`}
        aria-label="Session cost"
      >
        No usage observed yet.
      </div>
    );
  }

  return (
    <div className={`text-xs ${className ?? ""}`} aria-label="Session cost">
      <div className="flex items-center gap-3 px-3 py-1.5 tabular-nums">
        <span className="inline-flex items-center gap-1 font-medium">
          <DollarSign className="h-3 w-3 text-muted-foreground" />
          {formatCost(total.cost_usd)}
        </span>
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <Hash className="h-3 w-3" />
          {formatTokens(total.total_tokens)} tok
        </span>
        <span className="text-muted-foreground">
          ({total.calls} call{total.calls === 1 ? "" : "s"})
        </span>
      </div>
      {perModel && byModel.length > 1 && (
        <ul className="px-3 pb-1.5 space-y-0.5 text-[11px] text-muted-foreground tabular-nums">
          {byModel.map((row) => (
            <li key={row.model} className="flex items-center justify-between gap-3">
              <span className="font-mono truncate max-w-[14rem]">{row.model}</span>
              <span>
                {formatCost(row.cost_usd)} · {formatTokens(row.total_tokens)} tok · {row.calls}×
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
