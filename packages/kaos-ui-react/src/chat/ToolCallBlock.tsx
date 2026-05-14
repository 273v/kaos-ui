/**
 * Inline tool-call card rendered under an assistant `<Message>`.
 *
 * Visibility model:
 * - The summary row ALWAYS shows status + tool name + a 1-line result
 *   preview, so users see what happened without clicking.
 * - The expandable body shows args + the full result_preview the
 *   wire delivered (kaos-agents 0.1.0a1 truncates at 200 chars).
 * - `defaultOpen` makes the body start expanded — typically `true`
 *   for the in-flight assistant message and when the user has flipped
 *   the "verbose tools" toggle in the chat header.
 */

import { Check, ChevronDown, ChevronRight, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { ToolCallSummary } from "../lib/chat-state.js";

interface Props {
  call: ToolCallSummary;
  /** Start expanded. Default false. */
  defaultOpen?: boolean;
}

const PREVIEW_CHARS = 120;

function oneLine(text: string, cap = PREVIEW_CHARS): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > cap ? `${collapsed.slice(0, cap)}…` : collapsed;
}

export function ToolCallBlock({ call, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  // Honor a defaultOpen change that arrives after first render (e.g.,
  // the user flipped the verbose-tools toggle in the header).
  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  const Status = call.status === "running" ? Loader2 : call.status === "error" ? X : Check;
  const previewText = call.result_preview ? oneLine(call.result_preview) : null;

  return (
    <div className="rounded-md border border-border bg-card overflow-hidden text-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full text-left px-3 py-1.5 flex items-start gap-2 hover:bg-muted/60"
        title={`Tool: ${call.name}`}
      >
        <span className="mt-0.5 text-muted-foreground">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </span>
        <Status
          className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${
            call.status === "running"
              ? "animate-spin text-muted-foreground"
              : call.status === "error"
                ? "text-destructive"
                : "text-foreground"
          }`}
        />
        <span className="flex-1 min-w-0">
          <span className="font-mono text-xs font-medium">{call.name}</span>
          {previewText && (
            <span className="ml-2 text-xs text-muted-foreground italic">→ {previewText}</span>
          )}
          {!previewText && call.status === "running" && (
            <span className="ml-2 text-xs text-muted-foreground italic">running…</span>
          )}
        </span>
      </button>
      {open && (
        <div className="px-3 py-2 text-xs space-y-2 border-t border-border/70">
          {call.args_preview && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                arguments
              </div>
              <pre className="font-mono bg-muted rounded px-2 py-1 whitespace-pre-wrap break-words">
                {call.args_preview}
              </pre>
            </div>
          )}
          {call.result_preview && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                result
              </div>
              <pre className="font-mono bg-muted rounded px-2 py-1 whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
                {call.result_preview}
              </pre>
            </div>
          )}
          {call.status === "error" && !call.result_preview && (
            <div className="text-destructive italic">Tool call failed.</div>
          )}
        </div>
      )}
    </div>
  );
}
