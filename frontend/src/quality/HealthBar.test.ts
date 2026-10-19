import { describe, expect, it } from "vitest";
import { segmentWidths } from "./HealthBar";

const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);

describe("segmentWidths", () => {
  it("is all zeros, never NaN, for a 0 total", () => {
    expect(segmentWidths([0, 0, 0])).toEqual([0, 0, 0]);
    expect(segmentWidths([])).toEqual([]);
  });
  it("sums to 100 after rounding", () => {
    for (const c of [[1, 1, 1], [1, 2, 3], [2, 2, 3], [7, 0, 1], [1, 1000], [5]]) {
      const w = segmentWidths(c);
      expect(sum(w)).toBe(100);
      expect(w.every(Number.isFinite)).toBe(true);
    }
    expect(segmentWidths([1, 1, 1])).toEqual([34, 33, 33]);
  });
  it("gives 0 to empty segments and ignores bad input", () => {
    expect(segmentWidths([0, 4])).toEqual([0, 100]);
    expect(segmentWidths([NaN, -3, 2])).toEqual([0, 0, 100]);
  });
});
