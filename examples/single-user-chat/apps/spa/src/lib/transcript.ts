// Client-side transcript serializers.
//
// Both formats live entirely in the SPA — no server round-trip. The
// backend has a /v1/chat/sessions/{id}/transcript route, but as a
// stub for shareable-link use cases later (Phase 3+).

import type { SessionMeta } from "@/lib/api-types";
import type { ChatMessage } from "@/lib/chat-state";

export interface TranscriptInput {
  meta: SessionMeta;
  messages: ChatMessage[];
}

const ROLE_LABEL: Record<ChatMessage["role"], string> = {
  user: "You",
  assistant: "Assistant",
  tool: "Tool",
  error: "Error",
  system: "System",
};

export function toMarkdown(input: TranscriptInput): string {
  const lines: string[] = [];
  lines.push(`# ${input.meta.title}`);
  lines.push("");
  lines.push(`_${input.meta.model} · created ${input.meta.created_at}_`);
  lines.push("");
  lines.push("---");
  lines.push("");
  for (const m of input.messages) {
    lines.push(`**${ROLE_LABEL[m.role]}** — ${new Date(m.created_at).toISOString()}`);
    lines.push("");
    lines.push(m.content);
    if (m.tokens || m.cost_usd) {
      const tok = typeof m.tokens === "number" ? `${m.tokens.toLocaleString()} tok` : "";
      const cost = typeof m.cost_usd === "number" ? `$${m.cost_usd.toFixed(4)}` : "";
      lines.push("");
      lines.push(`> ${[tok, cost].filter(Boolean).join(" · ")}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

export function toJSON(input: TranscriptInput): string {
  return JSON.stringify(
    {
      session: input.meta,
      messages: input.messages,
      exported_at: new Date().toISOString(),
    },
    null,
    2,
  );
}

/** Trigger a browser download for the given text body. */
export function downloadText(filename: string, mimeType: string, body: string): void {
  const blob = new Blob([body], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function downloadMarkdown(input: TranscriptInput): void {
  const safe = input.meta.title.replace(/[^a-z0-9-_ ]/gi, "_").trim() || "transcript";
  downloadText(`${safe}.md`, "text/markdown", toMarkdown(input));
}

export function downloadJSON(input: TranscriptInput): void {
  const safe = input.meta.title.replace(/[^a-z0-9-_ ]/gi, "_").trim() || "transcript";
  downloadText(`${safe}.json`, "application/json", toJSON(input));
}
