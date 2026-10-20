import { afterEach, describe, expect, it, vi } from "vitest";
import { DRAWER_KEY, loadDrawerOpen, pickRoadmapDeal, roadmapSteps, saveDrawerOpen } from "./logic";

const states = (s: Parameters<typeof roadmapSteps>[0]) => roadmapSteps(s).map((x) => x.state);

describe("roadmapSteps", () => {
  it("marks done, current and later for an open deal", () => {
    expect(states("proposal")).toEqual(["done", "done", "current", "later", "later"]);
    expect(states("prospecting")).toEqual(["current", "later", "later", "later", "later"]);
  });
  it("completes everything when won", () => {
    expect(states("closed_won")).toEqual(["done", "done", "done", "done", "done"]);
  });
  it("shows closed lost for a lost deal", () => {
    const s = roadmapSteps("closed_lost");
    expect(s[4]).toEqual({ key: "closed", label: "closed lost", state: "lost" });
    expect(s.slice(0, 4).every((x) => x.state === "later")).toBe(true);
  });
});

describe("pickRoadmapDeal", () => {
  const d = (stage: "proposal" | "closed_won", created_on: string, is_closed: boolean) => ({ stage, created_on, is_closed });
  it("prefers the most recent open deal", () => {
    const r = pickRoadmapDeal([d("proposal", "2026-01-01", false), d("closed_won", "2026-05-01", true), d("proposal", "2026-03-01", false)]);
    expect(r?.created_on).toBe("2026-03-01");
  });
  it("falls back to the latest deal, or null", () => {
    expect(pickRoadmapDeal([d("closed_won", "2026-01-01", true), d("closed_won", "2026-02-01", true)])?.created_on).toBe("2026-02-01");
    expect(pickRoadmapDeal([])).toBeNull();
  });
});

describe("drawer persistence", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("is closed by default and when storage is missing", () => {
    expect(loadDrawerOpen()).toBe(false);
    expect(() => saveDrawerOpen(true)).not.toThrow();
  });
  it("round-trips through storage", () => {
    const m = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) });
    saveDrawerOpen(true);
    expect(m.get(DRAWER_KEY)).toBe("open");
    expect(loadDrawerOpen()).toBe(true);
    saveDrawerOpen(false);
    expect(loadDrawerOpen()).toBe(false);
  });
  it("survives storage that throws", () => {
    const boom = () => { throw new Error("denied"); };
    vi.stubGlobal("localStorage", { getItem: boom, setItem: boom, removeItem: boom });
    expect(loadDrawerOpen()).toBe(false);
    expect(() => saveDrawerOpen(true)).not.toThrow();
  });
});

import { navActive } from "./Nav";
describe("navActive", () => {
  it("keeps Flows apart from the other analysis pages", () => {
    expect(navActive("flows", "analysis")).toBe(true);
    expect(navActive("flows", "analysis/abc")).toBe(true);
    expect(navActive("flows", "analysis/workbooks/1")).toBe(false);
    expect(navActive("workbooks", "analysis/workbooks/1")).toBe(true);
    expect(navActive("deals", "deals/9")).toBe(true);
  });
});
