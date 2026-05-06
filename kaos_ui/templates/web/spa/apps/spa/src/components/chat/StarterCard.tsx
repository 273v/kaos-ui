/**
 * StarterCard — clickable hairline-border card on the empty state
 * grid. Hover lifts the border opacity, no shadow. Modeled after
 * Harvey's "Draft document / Review table" quick-action pills, but
 * slightly larger to act as starter-prompt slots.
 *
 * Replace the hard-coded prompts with `GET /v1/recipes` once that
 * endpoint ships in Phase B.
 */

import { cn } from "@{{KAOS_NPM_SLUG}}/ui/lib/utils";
import type { LucideIcon } from "lucide-react";

interface StarterCardProps {
  icon: LucideIcon;
  title: string;
  prompt: string;
  onSelect: (prompt: string) => void;
}

export function StarterCard({ icon: Icon, title, prompt, onSelect }: StarterCardProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(prompt)}
      className={cn(
        "group flex flex-col items-start gap-2 rounded-md border border-border bg-card p-4 text-left",
        "transition-colors hover:border-foreground/30 hover:bg-secondary",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
      )}
    >
      <Icon className="h-4 w-4 text-muted-foreground transition-colors group-hover:text-foreground" />
      <div className="space-y-1">
        <div className="text-sm font-medium">{title}</div>
        <div className="line-clamp-2 text-xs text-muted-foreground">{prompt}</div>
      </div>
    </button>
  );
}
