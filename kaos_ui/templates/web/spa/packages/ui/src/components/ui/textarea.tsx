/**
 * Textarea — shadcn-derived. Used as the chat composer.
 */
import type * as React from "react";

import { cn } from "@{{KAOS_NPM_SLUG}}/ui/lib/utils";

// `React.ComponentProps<"textarea">` includes `ref` (React 19 made
// refs a regular prop). The older `TextareaHTMLAttributes` type does
// not expose `ref` and breaks consumers that pass one through.
export function Textarea({
  className,
  ...props
}: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "flex min-h-[60px] w-full rounded-md border border-border bg-background px-3 py-2 text-sm",
        "placeholder:text-muted-foreground",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "resize-none",
        className,
      )}
      {...props}
    />
  );
}
