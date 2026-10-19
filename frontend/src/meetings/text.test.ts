import { describe, expect, it } from "vitest";
import { validateGraph, themesVsWinRateGraph, TEMPLATES } from "../flows/graph";
import { buildTurns, clampK, displaySegs, exactCount, legend, safeOffset } from "./text";
import type { ChunkOut } from "./types";

const ch = (id: string, seq: number, speaker: string | null, s: number, e: number): ChunkOut =>
  ({ id, seq, speaker, contact_id: null, user_id: null, char_start: s, char_end: e });
const join = (t: ReturnType<typeof buildTurns>) => t.flatMap((x) => x.segs.map((s) => s.text)).join("");

describe("buildTurns", () => {
  const text = "Ann: hello there. Bob: price is high. Ann: ok";
  it("groups by speaker and keeps all text", () => {
    const chunks = [ch("a", 0, "Ann", 5, 17), ch("b", 1, "Bob", 23, 37), ch("c", 2, "Ann", 42, 45)];
    const turns = buildTurns(text, chunks, [{ chunk_id: "b", theme_id: "t1", label: "Price" }]);
    expect(turns.map((t) => t.speaker)).toEqual(["Ann", "Bob", "Ann"]);
    expect(join(turns)).toBe(text);
    expect(turns[1]?.segs.find((s) => s.themeId === "t1")?.text).toBe("price is high.");
  });
  it("merges consecutive chunks of one speaker", () => {
    const turns = buildTurns("abcdef", [ch("a", 0, "X", 0, 3), ch("b", 1, "X", 3, 6)], []);
    expect(turns).toHaveLength(1);
    expect(join(turns)).toBe("abcdef");
  });
  it("handles overlapping and out-of-range chunks", () => {
    const turns = buildTurns("abcdefgh", [ch("a", 0, "X", 0, 5), ch("b", 1, "Y", 3, 7), ch("c", 2, "Y", 6, 99)], []);
    expect(join(turns)).toBe("abcdefgh");
  });
  it("never cuts a surrogate pair", () => {
    const t = "a😀b";
    expect(safeOffset(t, 2, "back")).toBe(1);
    expect(safeOffset(t, 2, "forward")).toBe(3);
    const turns = buildTurns(t, [ch("a", 0, "X", 0, 2), ch("b", 1, "Y", 2, 4)], []);
    expect(join(turns)).toBe(t);
    for (const s of turns.flatMap((x) => x.segs)) expect(s.text).not.toMatch(/^[\udc00-\udfff]|[\ud800-\udbff]$/);
  });
  it("falls back to one turn without chunks", () => {
    expect(buildTurns("hi", [], [])).toEqual([{ speaker: null, segs: [{ text: "hi", themeId: null, label: null }] }]);
    expect(buildTurns("", [], [])).toEqual([]);
  });
});

describe("legend and formatting", () => {
  it("dedupes themes in order and cycles classes", () => {
    const l = legend([
      { chunk_id: "1", theme_id: "a", label: "A" }, { chunk_id: "2", theme_id: "a", label: "A" },
      { chunk_id: "3", theme_id: "b", label: "B" },
    ]);
    expect(l.map((x) => x.cls)).toEqual(["th0", "th1"]);
  });
  it("formats", () => {
    expect(exactCount(1, "meeting")).toBe("1 meeting");
    expect(exactCount(2, "meeting")).toBe("2 meetings");
    expect(clampK(99)).toBe(30);
    expect(clampK(1)).toBe(2);
    expect(clampK(NaN)).toBe(8);
  });
});

describe("themes template", () => {
  it("passes the graph rules and filters on the label", () => {
    const g = themesVsWinRateGraph("Prix · budget");
    expect(validateGraph(g)).toEqual([]);
    expect(JSON.stringify(g)).toContain("Prix · budget");
    const t = TEMPLATES.find((x) => x.key === "themes");
    expect(t && validateGraph(t.build())).toEqual([]);
  });
});

describe("displaySegs", () => {
  const seg = (text: string, themeId: string | null = null) => ({ text, themeId, label: themeId ? "Price" : null });
  it("drops the repeated speaker prefix and the blank line before it", () => {
    expect(displaySegs({ speaker: "Ana Dupont", segs: [seg("\nAna Dupont: "), seg("Le prix est élevé.", "t1")] }))
      .toEqual([seg("Le prix est élevé.", "t1")]);
    expect(displaySegs({ speaker: "Ana Dupont", segs: [seg("**Ana Dupont:** Bonjour")] }).map((x) => x.text)).toEqual(["Bonjour"]);
    expect(displaySegs({ speaker: "Ana Dupont", segs: [seg("  **Ana Dupont**: Bonjour")] }).map((x) => x.text)).toEqual(["Bonjour"]);
  });
  it("leaves other text alone, and names with regex characters are safe", () => {
    expect(displaySegs({ speaker: "Ana Dupont", segs: [seg("Bob said: hi")] }).map((x) => x.text)).toEqual(["Bob said: hi"]);
    expect(displaySegs({ speaker: "J. (Rep)", segs: [seg("J. (Rep): ok")] }).map((x) => x.text)).toEqual(["ok"]);
    expect(displaySegs({ speaker: null, segs: [seg("\nfree text")] }).map((x) => x.text)).toEqual(["free text"]);
    expect(displaySegs({ speaker: "A", segs: [] })).toEqual([]);
  });
});
