import { describe, expect, it } from "vitest";
import { meaningOf, pct, sparkBars } from "./columns";

const c = (name: string, dtype: "number" | "integer" | "text" | "boolean" | "date" | "datetime" | "other", non_null = 100, n_unique = 50) =>
  ({ name, dtype, non_null, n_unique });

describe("meaningOf", () => {
  it("id wins on the last word of the name", () => {
    expect(meaningOf(c("account_id", "integer"))).toBe("id");
    expect(meaningOf(c("userId", "text"))).toBe("id");
    expect(meaningOf(c("paid", "text"))).not.toBe("id");
  });
  it("date, money, number", () => {
    expect(meaningOf(c("closed_at", "datetime"))).toBe("date");
    expect(meaningOf(c("deal_amount", "number"))).toBe("money");
    expect(meaningOf(c("age", "integer"))).toBe("number");
  });
  it("category needs few repeating values", () => {
    expect(meaningOf(c("stage", "text", 100, 5))).toBe("category");
    expect(meaningOf(c("note", "text", 100, 90))).toBe("text");
    expect(meaningOf(c("x", "text", 10, 8))).toBe("text");
    expect(meaningOf(c("won", "boolean"))).toBe("category");
    expect(meaningOf(c("blob", "other"))).toBe("text");
  });
});

describe("sparkBars", () => {
  it("draws non-finite values as empty bars, never NaN", () => {
    const bars = sparkBars([3, Number.NaN, Number.POSITIVE_INFINITY, 1], 40, 10);
    expect(bars.every((b) => Number.isFinite(b.x) && Number.isFinite(b.y) && Number.isFinite(b.h))).toBe(true);
    expect(bars.slice(0, 3).map((b) => b.h)).toEqual([10, 0, 0]);
    expect(bars[3].h).toBeCloseTo(10 / 3);
  });
  it("scales to the max", () => {
    const b = sparkBars([1, 2, 4], 30, 20, 0);
    expect(b.map((x) => x.h)).toEqual([5, 10, 20]);
    expect(b[2]?.y).toBe(0);
  });
  it("keeps tiny values visible and handles zeros and empty", () => {
    expect(sparkBars([1, 1000], 10, 10)[0]?.h).toBe(1);
    expect(sparkBars([0, 0], 10, 10).every((x) => x.h === 0)).toBe(true);
    expect(sparkBars([], 10, 10)).toEqual([]);
  });
});

describe("pct", () => {
  it("rounds and guards empty", () => {
    expect(pct(2, 3)).toBe(67);
    expect(pct(0, 0)).toBe(0);
  });
});
