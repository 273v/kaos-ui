// Pins the SSE parser semantics in @273v/kaos-ui-react/lib — the
// package owns the wire surface, but the template's vitest run is
// the regression net that catches a bad upgrade before the SPA boots
// against a real backend.

import { readSseStream } from "@273v/kaos-ui-react/lib";
import { describe, expect, it, vi } from "vitest";

function streamFromString(body: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(body));
      controller.close();
    },
  });
}

describe("readSseStream", () => {
  it("parses a single event with the kaos-agents wire shape", async () => {
    const body = 'event: text_delta\ndata: {"type":"text_delta","content":"hi"}\n\n';
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      event: "text_delta",
      data: { type: "text_delta", content: "hi" },
    });
  });

  it("parses a turn from text_delta start to turn_summary end", async () => {
    const body =
      'event: span\ndata: {"type":"span","subject":"turn","phase":"start"}\n\n' +
      'event: text_delta\ndata: {"type":"text_delta","content":"a"}\n\n' +
      'event: text_delta\ndata: {"type":"text_delta","content":"b"}\n\n' +
      'event: turn_summary\ndata: {"type":"turn_summary","text":"ab"}\n\n';
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const types: string[] = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      types.push(event.event);
    }
    expect(types).toEqual(["span", "text_delta", "text_delta", "turn_summary"]);
  });

  it("ignores comment / ping lines", async () => {
    const body =
      ": ping\n\n" + 'event: text_delta\ndata: {"type":"text_delta","content":"hi"}\n\n' + ": ping\n\n";
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
  });

  // Regression: ``sse-starlette`` (the backend we ship with this
  // template) emits CRLF line endings between events.
  // ``eventsource-parser`` handles all three SSE-spec line endings
  // (LF, CR, CRLF) — this test locks that in.
  it("parses CRLF-terminated events (sse-starlette wire format)", async () => {
    const body =
      'event: text_delta\r\ndata: {"type":"text_delta","content":"hi"}\r\n\r\n' +
      'event: turn_summary\r\ndata: {"type":"turn_summary","text":"hi"}\r\n\r\n';
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events.map((e) => e.event)).toEqual(["text_delta", "turn_summary"]);
    expect(events[0]?.data).toEqual({ type: "text_delta", content: "hi" });
  });

  // Regression: events split mid-UTF-8 codepoint across chunk
  // boundaries must still parse — eventsource-parser + TextDecoder
  // streaming mode handle this; a naive split() parser would corrupt
  // multi-byte characters or yield zero events.
  it("handles events split across chunk boundaries (UTF-8 safe)", async () => {
    const encoder = new TextEncoder();
    const full = encoder.encode(
      'event: text_delta\r\ndata: {"type":"text_delta","content":"café"}\r\n\r\n',
    );
    const idx1 = full.indexOf(0xc3); // first byte of é
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(full.slice(0, idx1 + 1));
        controller.enqueue(full.slice(idx1 + 1));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", () => Promise.resolve(new Response(stream, { status: 200 })));
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]?.data).toEqual({ type: "text_delta", content: "café" });
  });

  it("throws on non-200", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("nope", { status: 401 })));
    await expect(async () => {
      for await (const _ of readSseStream("/v1/sessions/test/messages")) {
        // never reached
      }
    }).rejects.toThrow();
  });
});
