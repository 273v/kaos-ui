/**
 * SSE consumer for the chat stream.
 *
 * Why we don't use the native `EventSource`:
 *   - It only supports GET; we POST the user message.
 *   - It can't send custom headers; we need `Authorization` for
 *     non-cookie deployments.
 *   - Same code path for cookie + bearer deployments.
 *
 * Why we don't roll our own SSE parser:
 *   - SSE has edge cases that bite naive parsers (CRLF vs LF,
 *     multi-line `data:` accumulation, `:` comment lines, chunk
 *     boundaries that split events, UTF-8 BOM at stream start).
 *   - `eventsource-parser` is the Vercel-maintained de-facto parser,
 *     used by Vercel `ai`, the OpenAI Node SDK, Anthropic's SDK.
 *
 * We keep our own `fetch()` so we control credentials, abort, and
 * the request body. `eventsource-parser` just parses bytes.
 */

import { type EventSourceMessage, createParser } from "eventsource-parser";

export interface StreamEvent {
  /** SSE `event:` field (defaults to `"message"` per spec). */
  event: string;
  /** Parsed JSON payload, or the raw string if it isn't valid JSON. */
  data: unknown;
  /** Optional SSE `id:` field, useful for resumption. */
  id?: string;
}

export interface ReadSseStreamOptions extends RequestInit {
  signal?: AbortSignal;
  /**
   * Custom fetch implementation. When omitted, the global `fetch` is
   * used. The transport's `fetch` should be threaded in here so
   * test stubs (msw) and retry wrappers see the SSE request too —
   * otherwise the streaming path silently bypasses
   * `<KaosUIProvider transport={{ fetch }}>`. See FIX-9.
   */
  fetch?: typeof fetch;
}

/**
 * Result of opening an SSE stream — an async iterator of parsed events
 * plus the run id we read off the response headers (when the backend
 * sent one).
 *
 * The run id is required for SSE resume so the SPA can stash it
 * synchronously, without waiting for the leading ``run_started``
 * envelope. Backends that don't set ``X-Kaos-Run-Id`` produce
 * ``runId === null`` and the SPA falls back to the envelope.
 */
export interface SseStreamHandle {
  events: AsyncIterableIterator<StreamEvent>;
  runId: string | null;
}

export async function readSseStream(
  url: string,
  init: ReadSseStreamOptions = {},
): Promise<SseStreamHandle> {
  const { fetch: customFetch, ...requestInit } = init;
  const f = customFetch ?? globalThis.fetch;
  const response = await f(url, {
    ...requestInit,
    credentials: "include",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      ...(requestInit.headers ?? {}),
    },
  });
  if (!response.ok || !response.body) {
    throw new Error(`SSE request failed: ${response.status}`);
  }

  // Stage 1 SSE-resume: the backend stamps the run id on every POST
  // response so the SPA can stash it before the first event lands.
  // Header name matches the backend constant `X-Kaos-Run-Id`.
  const runId = response.headers.get("X-Kaos-Run-Id");

  return { events: drainSseResponse(response), runId };
}

async function* drainSseResponse(
  response: Response,
): AsyncIterableIterator<StreamEvent> {
  if (!response.body) {
    // Defensive — readSseStream already throws on a missing body,
    // but TS doesn't carry that invariant through into the generator.
    return;
  }

  // Buffer parser output so the async generator can yield one event
  // per `next()` call. The parser's callback model doesn't compose
  // with `yield` directly; this queue bridges them.
  const queue: StreamEvent[] = [];
  let resolveNext: (() => void) | null = null;
  let done = false;

  const wakeUp = () => {
    if (resolveNext) {
      const r = resolveNext;
      resolveNext = null;
      r();
    }
  };

  const parser = createParser({
    onEvent(message: EventSourceMessage) {
      const event: StreamEvent = {
        event: message.event ?? "message",
        data: tryParseJson(message.data),
      };
      if (message.id) event.id = message.id;
      queue.push(event);
      wakeUp();
    },
    onError() {
      // Parser errors are non-fatal per the SSE spec; the next event
      // will re-sync. We deliberately don't surface them.
    },
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let readerError: Error | null = null;

  // Drive the reader on a separate microtask chain so the consumer
  // can pull events as they arrive. Reader errors (server disconnect,
  // network drop) are captured here and re-thrown from the next pull
  // — otherwise the consumer would hang on the UI's "Thinking…" state.
  (async () => {
    try {
      while (true) {
        const { value, done: readerDone } = await reader.read();
        if (readerDone) break;
        parser.feed(decoder.decode(value, { stream: true }));
        wakeUp();
      }
    } catch (err) {
      readerError = err instanceof Error ? err : new Error(String(err));
    } finally {
      done = true;
      wakeUp();
    }
  })();

  while (true) {
    if (queue.length > 0) {
      yield queue.shift() as StreamEvent;
      continue;
    }
    if (done) {
      if (readerError) throw readerError;
      return;
    }
    await new Promise<void>((resolve) => {
      resolveNext = resolve;
    });
  }
}

function tryParseJson(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
}
