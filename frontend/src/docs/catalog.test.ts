import { describe, expect, it } from "vitest";
import { DOCS, docFor, searchDocs } from "./catalog";

// Messages copied from the backend (stats/gates.py, flows/blocks/*): each must reach its page.
const CASES: [string, string][] = [
  ["n = 12 < 30", "small-n"],
  ["group: n = 4 < 30", "small-n"],
  ["only 4 wins (< 10)", "few-wins"],
  ["rest: only 2 losses (< 10)", "few-wins"],
  ["group: win count unknown", "win-count-unknown"],
  ["CI ±18.0 pts > ±15 pts", "ci-wide"],
  ["rest: CI ±45% of the median > ±30%", "ci-wide"],
  ["CI not computable", "ci-not-computable"],
  ["median is 0: relative CI undefined", "ci-not-computable"],
  ["q = 0.21 >= 0.05", "not-significant"],
  ["no p-value", "not-significant"],
  ["difference CI [-3.0, +9.5] pts includes 0", "includes-zero"],
  ["rows were duplicated by an upstream join, so n is inflated", "multiplied"],
  ["rows multiplied by the join (more output rows than the left input); counts downstream are inflated", "multiplied"],
  ["test set too small (n = 18 < 30)", "test-small"],
  ["only 6 positive rows in test (< 10)", "few-classes"],
  ["AUC CI not computable (one class in test)", "ci-not-computable"],
  ["R2 CI low -0.02 <= 0 (no better than predicting the mean)", "no-better-than-baseline"],
  ["AUC CI low 0.480 <= 0.5 (includes chance)", "no-better-than-baseline"],
  ["accuracy CI low 0.610 <= majority-class baseline 0.640", "no-better-than-baseline"],
  ["test rows may overlap the training rows: connect train and test from the same split block", "leak"],
  ["rows capped at 200000", "rows-capped"],
  ["12 rows with a missing group or outcome excluded", "rows-excluded"],
  ["3 rows with a missing x dropped", "rows-excluded"],
  ["bootstrap resamples lowered from 2000 to 400 to bound the work", "bootstrap-lowered"],
  ["7 pivot column values dropped (max_columns = 50)", "view-truncated"],
  ["chart truncated to 2000 points", "view-truncated"],
];

describe("docFor", () => {
  it.each(CASES)("%s -> %s", (text, id) => {
    expect(docFor(text)?.id).toBe(id);
  });
  it("returns null for unknown text", () => {
    expect(docFor("something else entirely")).toBeNull();
  });
});

describe("catalog", () => {
  it("has unique ids", () => {
    expect(new Set(DOCS.map((d) => d.id)).size).toBe(DOCS.length);
  });
  it("searches every field", () => {
    expect(searchDocs("benjamini").map((d) => d.id)).toContain("q-value");
    expect(searchDocs("")).toHaveLength(DOCS.length);
  });
});
