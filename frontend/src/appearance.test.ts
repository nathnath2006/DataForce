import { describe, expect, it } from "vitest";
import { applyAppearance, readAppearance, saveAppearance } from "./appearance";

const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); } }; };

describe("appearance", () => {
  it("round-trips and ignores invalid values", () => {
    const s = mem();
    expect(readAppearance(s)).toEqual({ density: "comfortable", text: "standard", motion: "system" });
    saveAppearance({ density: "compact", text: "large", motion: "reduced" }, s);
    expect(readAppearance(s)).toEqual({ density: "compact", text: "large", motion: "reduced" });
    s.setItem("df-appearance", "{\"density\":\"huge\"}");
    expect(readAppearance(s).density).toBe("comfortable");
    s.setItem("df-appearance", "not json");
    expect(readAppearance(s).text).toBe("standard");
  });
  it("sets only the non-default attributes", () => {
    const root = { dataset: {} as Record<string, string | undefined> };
    applyAppearance({ density: "compact", text: "standard", motion: "system" }, root);
    expect(root.dataset).toEqual({ density: "compact" });
    applyAppearance({ density: "comfortable", text: "standard", motion: "system" }, root);
    expect(root.dataset).toEqual({});
  });
});
