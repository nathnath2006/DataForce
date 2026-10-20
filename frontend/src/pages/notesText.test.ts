import { describe, expect, it } from "vitest";
import { noteSnippet, noteTitle } from "./notesText";

describe("note list text", () => {
  it("uses the first non-empty line as the title", () => {
    expect(noteTitle("\n  Call back Tuesday \nabout pricing")).toBe("Call back Tuesday");
    expect(noteTitle("   ")).toBe("Empty");
    expect(noteTitle("x".repeat(80), 10)).toBe("xxxxxxxxx…");
  });
  it("joins the other lines as the snippet", () => {
    expect(noteSnippet("Title\nline one\n\nline two")).toBe("line one line two");
    expect(noteSnippet("Only a title")).toBe("");
  });
});
