import { describe, expect, it } from "vitest";
import { parseAnswer } from "./refs";

const cites = [{ ref: "F3", kind: "fact", label: "Won amount" }, { ref: "N5", kind: "note", label: "Note 5 May" }];

describe("parseAnswer", () => {
  it("splits text and refs, using citation labels", () => {
    expect(parseAnswer("Won 3 deals [F3] and a call [N5].", cites)).toEqual([
      { type: "text", text: "Won 3 deals " },
      { type: "ref", ref: "F3", label: "Won amount", known: true },
      { type: "text", text: " and a call " },
      { type: "ref", ref: "N5", label: "Note 5 May", known: true },
      { type: "text", text: "." },
    ]);
  });
  it("keeps unknown refs as unknown chips", () => {
    expect(parseAnswer("x [D9]", cites)[1]).toEqual({ type: "ref", ref: "D9", label: "D9", known: false });
  });
  it("never interprets HTML and ignores lookalikes", () => {
    const s = parseAnswer("<img src=x onerror=1> [F3x] [f3] [F]", cites);
    expect(s).toEqual([{ type: "text", text: "<img src=x onerror=1> [F3x] [f3] [F]" }]);
  });
  it("handles empty and ref-only input", () => {
    expect(parseAnswer("", cites)).toEqual([]);
    expect(parseAnswer("[F3]", [])).toHaveLength(1);
  });
});
