import { describe, expect, it } from "vitest";
import { BLOCKS, PORTS, TEMPLATES, defaultConfig, validateCleaning, validateGraph } from "./graph";

describe("cleaning blocks", () => {
  it("are in the Cleaning group with ports and defaults", () => {
    for (const t of ["standardize", "regex"] as const) {
      expect(BLOCKS.find((b) => b.type === t)?.group).toBe("Cleaning");
      expect(PORTS[t]).toEqual({ inputs: ["in"], outputs: ["out"] });
      expect(defaultConfig(t).type).toBe(t);
    }
    expect(defaultConfig("standardize")).toMatchObject({ output: "overwrite", country: "FR", mapping: {} });
    expect(defaultConfig("regex")).toMatchObject({ mode: "extract", split_into: 3, ignore_case: false });
  });
  it("validates standardize", () => {
    const c = defaultConfig("standardize");
    expect(validateCleaning(c)).toContain("pick at least one column");
    if (c.type !== "standardize") throw new Error();
    expect(validateCleaning({ ...c, columns: ["a"] })).toEqual([]);
    expect(validateCleaning({ ...c, columns: ["a"], operations: ["map_values"] })).toContain("map_values needs at least one pair");
    const big = Object.fromEntries(Array.from({ length: 201 }, (_, i) => [`k${i}`, "v"]));
    expect(validateCleaning({ ...c, columns: ["a"], mapping: big })).toContain("the value map has at most 200 pairs");
  });
  it("validates regex", () => {
    const c = defaultConfig("regex");
    if (c.type !== "regex") throw new Error();
    const ok = { ...c, column: "e", pattern: "@(?P<d>[^@]+)$" };
    expect(validateCleaning(ok)).toEqual([]);
    expect(validateCleaning({ ...ok, pattern: "a".repeat(201) })).toContain("the pattern has at most 200 characters");
    expect(validateCleaning({ ...ok, pattern: "(a+)+" }).join()).toMatch(/catastrophically/);
    expect(validateCleaning({ ...ok, pattern: "(a)" }).join()).toMatch(/named group/);
  });
  it("the Clean contacts template is a valid flow", () => {
    const t = TEMPLATES.find((x) => x.key === "clean_contacts");
    expect(t).toBeDefined();
    expect(validateGraph(t!.build())).toEqual([]);
  });
});
