import type { TurnStatus as Status } from "@/lib/chat-state";

interface Props {
  status: Status;
}

/** Italic muted pill shown while the agent is mid-turn. */
export function TurnStatus({ status }: Props) {
  if (status.kind === "idle") return null;

  const label =
    status.kind === "thinking"
      ? "Thinking…"
      : status.kind === "tool"
        ? `Running tool: ${status.tool}`
        : status.kind === "step"
          ? `Step ${status.index}`
          : status.kind === "error"
            ? status.what
            : "Working…";

  const tone = status.kind === "error" ? "text-destructive" : "text-muted-foreground";

  return (
    <div className="py-2 text-xs italic" role="status" aria-live="polite">
      <span className={tone}>{label}</span>
    </div>
  );
}
