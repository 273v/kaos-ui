/**
 * SSE consumer for the chat stream.
 *
 * The backend serves SSE at ``POST /v1/sessions/{id}/messages``.
 *
 * Why we don't use the native ``EventSource``:
 * - It only supports GET (we POST the user message).
 * - It can't send custom headers (we sometimes need auth headers for
 *   non-cookie deployments).
 * - Browsers won't send httpOnly cookies cross-origin, but our same-
 *   origin proxy makes cookies work — still, we want one code path.
 *
 * Why we don't roll our own SSE parser:
 * - SSE has many edge cases that bite naive parsers: CRLF vs LF event
 *   separators (``sse-starlette`` emits CRLF), multi-line ``data:``
 *   accumulation, ``:`` comment / ping lines, ``event:`` / ``id:`` /
 *   ``retry:`` fields, UTF-8 BOM at stream start, and chunk boundaries
 *   that split events.
 * - ``eventsource-parser`` (Vercel-maintained, used by Vercel ``ai``,
 *   the OpenAI Node SDK, Anthropic's SDK, etc.) is the de-facto
 *   parser. ~3M weekly downloads. We just feed it bytes.
 *
 * We keep our own ``fetch()`` so we control credentials, abort, and
 * the request body. ``eventsource-parser`` only does the parsing.
 */

import { createParser, type EventSourceMessage } from "eventsource-parser";

export interface StreamEvent {
  /** SSE ``event:`` field (defaults to ``message`` per spec). */
  event: string;
  /** Parsed JSON payload, or the raw string if it isn't valid JSON. */
  data: unknown;
  /** Optional SSE ``id:`` field, useful for resumption. */
  id?: string;
}

export interface ReadSseStreamOptions extends RequestInit {
  /** Abort the in-flight stream. Wired into ``fetch``'s ``signal``. */
  signal?: AbortSignal;
}

export async function* readSseStream(
  url: string,
  init: ReadSseStreamOptions = {},
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

  // Buffer parser output so the async generator can yield one event
  // per ``next()`` call. ``eventsource-parser``'s callback model
  // doesn't compose with ``yield`` directly; this queue bridges them.
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
      // Parser errors are non-fatal for the spec; the next event will
      // re-sync. We deliberately don't surface them.
    },
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let readerError: Error | null = null;

  // Drive the reader on a separate microtask chain so the consumer
  // can pull events as they arrive. MEDIUM #4 — pre-fix, errors were
  // swallowed, leaving the consumer waiting forever and the UI stuck
  // on "Thinking…". We now capture and re-throw on the next pull.
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
