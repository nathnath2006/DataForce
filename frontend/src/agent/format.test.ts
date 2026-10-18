import { describe, expect, it } from "vitest";
import { callSummary, desktopSnippet, shortDescription } from "./format";

describe("agent format", () => {
  it("formats the desktop snippet as indented JSON", () => {
    const cfg = { mcpServers: { "dataforce-x": { command: "/a/dataforce", args: ["mcp", "--workspace", "x"] } } };
    const out = desktopSnippet({ claude_desktop: cfg, claude_code: "" });
    expect(JSON.parse(out)).toEqual(cfg);
    expect(out.split("\n")[1]).toBe('  "mcpServers": {');
  });
  it("keeps the first sentence", () => {
    expect(shortDescription("Counts things.\n More detail here.")).toBe("Counts things.");
    expect(shortDescription("x".repeat(300), 10)).toHaveLength(10);
  });
  it("summarises a call", () => {
    expect(callSummary({ at: "", tool: "t", ok: true, rows: 1, duration_ms: 12 })).toBe("t: ok, 1 row, 12 ms");
    expect(callSummary({ at: "", tool: "t", ok: false, rows: null, duration_ms: null })).toBe("t: error");
  });
});
