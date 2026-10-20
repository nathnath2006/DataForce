import { describe, expect, it, vi } from "vitest";
import { cacheClear, cacheGet, cacheSet, invalidate, isFresh, onInvalidate } from "./cache";
import { pagerLabel } from "../table/Pager";

describe("cache", () => {
  it("is fresh for 30 s and invalidates by prefix", () => {
    cacheClear();
    cacheSet("/w/a/deals?x=1", 1);
    cacheSet("/w/b/deals", 2);
    const e = cacheGet("/w/a/deals?x=1");
    expect(isFresh(e)).toBe(true);
    expect(isFresh(e, Date.now() + 31_000)).toBe(false);
    const seen = vi.fn();
    const off = onInvalidate(seen);
    invalidate("/w/a/");
    off();
    expect(cacheGet("/w/a/deals?x=1")).toBeUndefined();
    expect(cacheGet("/w/b/deals")).toBeDefined();
    expect(seen).toHaveBeenCalledWith("/w/a/");
  });
});

describe("pagerLabel", () => {
  it("formats the range with thousands separators", () => {
    expect(pagerLabel(0, 50, 1234)).toBe("1–50 of 1,234");
    expect(pagerLabel(1200, 34, 1234)).toBe("1,201–1,234 of 1,234");
    expect(pagerLabel(0, 0, 0)).toBe("0 results");
  });
});
