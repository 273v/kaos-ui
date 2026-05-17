/**
 * VIS-4b — `repairAndParseJson` recovers partial records from
 * kaos-agents wire-truncated JSON. Pinning the cases that matter
 * for tool chip rendering so the repair stays robust.
 */

import { repairAndParseJson } from "@273v/kaos-ui-react/chat";
import { describe, expect, it } from "vitest";

describe("repairAndParseJson", () => {
  it("returns null for empty input", () => {
    expect(repairAndParseJson("")).toBeNull();
    expect(repairAndParseJson(undefined)).toBeNull();
  });

  it("returns the parse result unchanged when input is valid JSON", () => {
    expect(repairAndParseJson('{"a":1}')).toEqual({ a: 1 });
    expect(repairAndParseJson('[1,2,3]')).toEqual([1, 2, 3]);
  });

  it("recovers the first complete record when an inner string is truncated", () => {
    // Simulates kaos-agents' 200-char wire truncation landing mid-string
    // on the second field's value.
    const truncated =
      '{"results": [{"document_number": "2024-30494", "title": "EDGAR Filer';
    const out = repairAndParseJson<{ results: Array<Record<string, unknown>> }>(truncated);
    expect(out).not.toBeNull();
    expect(out?.results).toHaveLength(1);
    expect(out?.results[0]).toEqual({ document_number: "2024-30494" });
  });

  it("recovers multiple fields when a later field's string is truncated", () => {
    const truncated =
      '{"results": [{"document_number": "2024-30494", "title": "EDGAR Filer Access and Account Management", "type": "Rule", "publication_date""';
    const out = repairAndParseJson<{ results: Array<Record<string, unknown>> }>(truncated);
    expect(out).not.toBeNull();
    const first = out?.results[0];
    expect(first?.document_number).toBe("2024-30494");
    expect(first?.title).toBe("EDGAR Filer Access and Account Management");
    expect(first?.type).toBe("Rule");
    expect(first).not.toHaveProperty("publication_date");
  });

  it("recovers multiple complete records before truncation", () => {
    const truncated =
      '{"results": [{"document_number": "A", "type": "Rule"}, {"document_number": "B", "type": "Notice"}, {"document_number": "C", "title": "incomplete';
    const out = repairAndParseJson<{ results: Array<Record<string, unknown>> }>(truncated);
    // A and B are fully recovered; C survives with whatever fields
    // landed before the unfinished string (here just document_number).
    expect(out?.results).toHaveLength(3);
    expect(out?.results[0]).toEqual({ document_number: "A", type: "Rule" });
    expect(out?.results[1]).toEqual({ document_number: "B", type: "Notice" });
    expect(out?.results[2]).toEqual({ document_number: "C" });
  });

  it("recovers a number value that was completed", () => {
    const truncated = '{"count": 42, "rows": [{"id":1},{"id":2},{"id":';
    const out = repairAndParseJson<{ count: number; rows: Array<{ id: number }> }>(truncated);
    expect(out?.count).toBe(42);
    expect(out?.rows).toEqual([{ id: 1 }, { id: 2 }]);
  });

  it("handles a true/false/null literal cleanly", () => {
    const truncated = '{"ok": true, "err": null, "more": [{"x":';
    const out = repairAndParseJson<{ ok: boolean; err: null }>(truncated);
    expect(out?.ok).toBe(true);
    expect(out?.err).toBeNull();
  });

  it("returns null when nothing can be safely recovered", () => {
    // Truncated before any complete field.
    expect(repairAndParseJson('{"a":')).toBeNull();
    expect(repairAndParseJson('{"a":"unfin')).toBeNull();
  });

  it("ignores escaped quotes inside string values", () => {
    const ok = repairAndParseJson<{ a: string; b: number }>('{"a":"hello \\"world\\"", "b":1}');
    expect(ok).toEqual({ a: 'hello "world"', b: 1 });
  });
});
