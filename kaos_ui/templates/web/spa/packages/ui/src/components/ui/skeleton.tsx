/**
 * Skeleton — animated placeholder. Used as the streaming-indicator
 * (a 1px caret + skeleton block, no chat-bubble dots).
 */
import type * as React from "react";

import { cn } from "@{{KAOS_NPM_SLUG}}/ui/lib/utils";

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}
