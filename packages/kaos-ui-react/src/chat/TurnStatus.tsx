/**
 * Italic muted pill shown while the agent is mid-turn. Driven by the
 * `TurnStatusKind` discriminator emitted from the `applyEvent` reducer.
 */

import type { TurnStatusKind } from "../lib/chat-state.js";

interface Props {
  status: TurnStatusKind;
}

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
    <output className="block py-2 text-xs italic" aria-live="polite">
      <span className={tone}>{label}</span>
    </output>
  );
}
