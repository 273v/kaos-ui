import { Check, Loader2, X } from "lucide-react";

import type { ToolCallSummary } from "@/lib/chat-state";

interface Props {
  call: ToolCallSummary;
}

/**
 * Collapsed inline tool-call card per UX-LANGUAGE.md § 4.4.
 * Native <details> for accessibility — no custom toggle JS.
 */
export function ToolCallBlock({ call }: Props) {
  const Icon = call.status === "running" ? Loader2 : call.status === "error" ? X : Check;

  return (
    <details className="rounded-md border border-border bg-card overflow-hidden text-sm">
      <summary
        className="cursor-pointer select-none px-3 py-1.5 flex items-center gap-2 hover:bg-muted/60"
        title={`Tool: ${call.name}`}
      >
        <Icon
          className={
            "h-3.5 w-3.5 " +
            (call.status === "running"
              ? "animate-spin text-muted-foreground"
              : call.status === "error"
                ? "text-destructive"
                : "text-foreground")
          }
        />
        <span className="font-medium">{call.name}</span>
        <span className="text-xs text-muted-foreground">{call.status}</span>
      </summary>
      <div className="px-3 py-2 text-xs space-y-2 border-t border-border/70">
        {call.args_preview && (
          <div>
            <div className="text-muted-foreground mb-1">arguments</div>
            <pre className="font-mono bg-secondary rounded px-2 py-1 whitespace-pre-wrap break-words">
              {call.args_preview}
            </pre>
          </div>
        )}
        {call.result_preview && (
          <div>
            <div className="text-muted-foreground mb-1">result</div>
            <pre className="font-mono bg-secondary rounded px-2 py-1 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
              {call.result_preview}
            </pre>
          </div>
        )}
      </div>
    </details>
  );
}
