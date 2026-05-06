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
    const body = "event: TextDelta\ndata: {\"text\": \"hi\"}\n\n";
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
      "event: TextDelta\ndata: {\"text\": \"a\"}\n\n" +
      "event: TextDelta\ndata: {\"text\": \"b\"}\n\n" +
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
    const body =
      ": ping\n\n" +
      "event: TextDelta\ndata: {\"text\":\"hi\"}\n\n" +
      ": ping\n\n";
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(streamFromString(body), { status: 200 })),
    );
    const events: Array<{ event: string; data: unknown }> = [];
    for await (const event of readSseStream("/v1/sessions/test/messages")) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
  });

  it("throws on non-200", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response("nope", { status: 401 })),
    );
    await expect(async () => {
      for await (const _ of readSseStream("/v1/sessions/test/messages")) {
        // never reached
      }
    }).rejects.toThrow();
  });
});
