// Client-side transcript serializers.
//
// Both formats live entirely in the SPA — no server round-trip. The
// backend has a /v1/chat/sessions/{id}/transcript route, but as a
// stub for shareable-link use cases later (Phase 3+).

import type { ChatMessage } from "@273v/kaos-ui-react/lib";

import type { SessionMeta } from "@/lib/api-types";

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

function formatLatency(ms: number | undefined): string | null {
  if (typeof ms !== "number") return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60_000);
  const sec = Math.round((ms % 60_000) / 1000);
  return `${min}m${sec.toString().padStart(2, "0")}s`;
}

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

    // Inline tool-call cards as fenced blocks under the assistant
    // message so a markdown reader sees what was invoked + what came
    // back, not just the prose.
    if (m.tool_calls && m.tool_calls.length > 0) {
      for (const tc of m.tool_calls) {
        lines.push("");
        lines.push(`> **Tool call** — \`${tc.name}\` · ${tc.status}`);
        if (tc.args_preview) {
          lines.push("> ");
          lines.push("> ```");
          for (const argline of tc.args_preview.split("\n")) {
            lines.push(`> ${argline}`);
          }
          lines.push("> ```");
        }
        if (tc.result_preview) {
          lines.push("> ");
          lines.push("> ```");
          for (const rline of tc.result_preview.split("\n")) {
            lines.push(`> ${rline}`);
          }
          lines.push("> ```");
        }
      }
    }

    // Per-turn stats footer.
    const stats: string[] = [];
    const latency = formatLatency(m.latency_ms);
    if (latency) stats.push(latency);
    if (typeof m.tokens === "number") stats.push(`${m.tokens.toLocaleString()} tok`);
    if (typeof m.input_tokens === "number" && typeof m.output_tokens === "number") {
      stats.push(`(${m.input_tokens} in / ${m.output_tokens} out)`);
    }
    if (typeof m.cost_usd === "number") stats.push(`$${m.cost_usd.toFixed(4)}`);
    if (m.tool_calls && m.tool_calls.length > 0) {
      stats.push(`${m.tool_calls.length} tool${m.tool_calls.length === 1 ? "" : "s"}`);
    }
    if (stats.length > 0) {
      lines.push("");
      lines.push(`> ${stats.join(" · ")}`);
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
