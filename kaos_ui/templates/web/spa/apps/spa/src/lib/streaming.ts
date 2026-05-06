/**
 * SSE consumer for the chat stream.
 *
 * The backend serves SSE at `POST /v1/sessions/{id}/messages`. Browsers'
 * native `EventSource` doesn't support custom headers / methods other
 * than GET, and httpOnly cookies are sent automatically only on
 * same-origin requests. We use `fetch` + ReadableStream + a manual SSE
 * parser instead.
 *
 * Pairs with TanStack Query's `experimental_streamedQuery` (see
 * kaos-ui/docs/templates/spa.md for the canonical usage).
 */

export interface StreamEvent {
  event: string;
  data: unknown;
}

export async function* readSseStream(
  url: string,
  init: RequestInit = {},
): AsyncIterableIterator<StreamEvent> {
  const response = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok || !response.body) {
    throw new Error(`SSE request failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = parseSseBlock(block);
      if (event) yield event;
    }
  }
}

function parseSseBlock(block: string): StreamEvent | null {
  const lines = block.split("\n");
  let eventName = "message";
  let data = "";
  for (const line of lines) {
    if (line.startsWith(":")) continue; // SSE comment / ping
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) data += `${line.slice(5).trim()}\n`;
  }
  if (!data) return null;
  try {
    return { event: eventName, data: JSON.parse(data.trim()) };
  } catch {
    return { event: eventName, data: data.trim() };
  }
}
