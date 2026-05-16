/**
 * Shared scratchpad-tag stripping for assistant text.
 *
 * Used by both the live SSE reducer (event-handler.ts) AND the
 * route-level history hydration mapper (apps/spa). Same patterns
 * either way so a user reading their transcript NEVER sees the
 * `[/response]` / `</response>` / `<function_calls>{...}</function_calls>`
 * artifacts that instruction-tuned models hallucinate when tool
 * binding falls off the native path.
 *
 * The root-cause fix lives in `kaos-agents 0.1.0a5+` (native JSONCodec
 * in BaseAgent._simple_respond instead of ChatCodec); this strip is
 * belt-and-suspenders for sessions that were CREATED with older
 * kaos-agents and persisted dirty bytes into session memory.
 */

// `<function_calls>[...]</function_calls>` — Claude emits its
// function-calling syntax as text when tool binding is not using
// the native tool_use path. Strip the WHOLE block (opener + JSON
// body + closer), not just the closer, because the body is a JSON
// array the user shouldn't see.
const SCRATCHPAD_BLOCK_RE = /<function_calls>[\s\S]*?<\/function_calls>/g;

// `[/name]` / `</name>` — single-line opener-anchored field-marker
// closers hallucinated by Haiku-class models. Conservative: only
// `\w+` slugs in brackets so literal text like `[/usr/local]` or
// `</a href="...">` is left alone.
const SCRATCHPAD_TAG_RE = /\[\/\w+\]|<\/\w+>/g;

export function stripScratchpadTags(text: string): string {
  if (!text) return text;
  return text.replace(SCRATCHPAD_BLOCK_RE, "").replace(SCRATCHPAD_TAG_RE, "");
}
