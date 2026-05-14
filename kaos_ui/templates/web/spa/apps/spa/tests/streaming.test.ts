import { describe, expect, it, vi } from "vitest";
import { readSseStream } from "@/lib/streaming";

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
  it("parses a single event", async () => {
    const body = 'event: TextDelta\ndata: {"text": "hi"}\n\n';
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ event: "TextDelta", data: { text: "hi" } });
  });

  it("parses multiple events split across writes", async () => {
    const body =
      "event: TurnStart\ndata: {}\n\n" +
      'event: TextDelta\ndata: {"text": "a"}\n\n' +
      'event: TextDelta\ndata: {"text": "b"}\n\n' +
      "event: TurnComplete\ndata: {}\n\n";
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push({ event: event.event });
    }
    expect(events.map((e) => e.event)).toEqual([
      "TurnStart",
      "TextDelta",
      "TextDelta",
      "TurnComplete",
    ]);
  });

  it("ignores comment / ping lines", async () => {
    const body = ": ping\n\n" + 'event: TextDelta\ndata: {"text":"hi"}\n\n' + ": ping\n\n";
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
  // template) emits CRLF line endings between events. A naive parser
  // that only looks for ``\n\n`` would silently deliver zero events.
  // ``eventsource-parser`` handles all three SSE-spec line endings
  // (LF, CR, CRLF) — this test locks that in.
  it("parses CRLF-terminated events (sse-starlette wire format)", async () => {
    const body =
      'event: text_delta\r\ndata: {"content":"hi","type":"text_delta"}\r\n\r\n' +
      'event: turn_complete\r\ndata: {"text":"hi","type":"turn_complete"}\r\n\r\n';
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events.map((e) => e.event)).toEqual(["text_delta", "turn_complete"]);
    expect(events[0]?.data).toEqual({ content: "hi", type: "text_delta" });
  });

  // Regression: events can be split across chunks at arbitrary byte
  // boundaries — including in the middle of a multi-byte UTF-8 codepoint.
  // ``eventsource-parser`` + ``TextDecoder({stream:true})`` handle this;
  // a naive ``decode().split()`` parser would corrupt characters or
  // yield zero events when the separator straddles a chunk boundary.
  it("handles events split across chunk boundaries (UTF-8 safe)", async () => {
    const encoder = new TextEncoder();
    // "café" is c (1B) + a (1B) + f (1B) + é (2B U+00E9 -> C3 A9).
    const full = encoder.encode(
      'event: text_delta\r\ndata: {"content":"café","type":"text_delta"}\r\n\r\n',
    );
    // Split mid-UTF-8 (between the two bytes of é) AND inside the
    // event separator.
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
    expect(events[0]?.data).toEqual({ content: "café", type: "text_delta" });
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
