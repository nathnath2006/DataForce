import { describe, expect, it } from "vitest";
import { applyTheme, nextTheme, readTheme, saveTheme } from "./theme";

const mem = (init?: string) => {
  let v = init ?? null;
  return { getItem: () => v, setItem: (_k: string, x: string) => { v = x; } };
};
const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };

describe("theme", () => {
  it("cycles system, light, dark", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });
  it("reads and falls back to system", () => {
    expect(readTheme(mem("dark"))).toBe("dark");
    expect(readTheme(mem("purple"))).toBe("system");
    expect(readTheme(broken)).toBe("system");
    expect(readTheme(null)).toBe("system");
  });
  it("saving never throws", () => {
    const m = mem();
    saveTheme("light", m);
    expect(readTheme(m)).toBe("light");
    expect(() => saveTheme("dark", broken)).not.toThrow();
  });
  it("applies to the root dataset", () => {
    const root: { dataset: Record<string, string | undefined> } = { dataset: {} };
    applyTheme("dark", root);
    expect(root.dataset["theme"]).toBe("dark");
    applyTheme("system", root);
    expect(root.dataset["theme"]).toBeUndefined();
  });
});
