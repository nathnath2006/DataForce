import { describe, expect, it, vi } from "vitest";
import { alphaChannel, progressOf, sampleTargets, slugify, stepStates } from "./logic";
import { refreshUntil } from "../data/refresh";

describe("slugify", () => {
  it("makes a lowercase dashed slug", () => {
    expect(slugify("Acme Sales — EU 2026!")).toBe("acme-sales-eu-2026");
    expect(slugify("  --  ")).toBe("");
    expect(slugify("a".repeat(100))).toHaveLength(64);
  });
});

const st = (o: Partial<Parameters<typeof stepStates>[0] & object>) =>
  ({ state: "preparing", step: null, done: 0, total: 8, error: null, ...o }) as never;

describe("stepStates", () => {
  it("marks earlier steps done and the reported one current", () => {
    const s = stepStates(st({ step: "deals", done: 4 }));
    expect(s.slice(0, 4)).toEqual(["done", "done", "done", "done"]);
    expect(s[4]).toBe("current");
    expect(s.slice(5)).toEqual(["todo", "todo", "todo"]);
  });
  it("falls back to done, and to the first step before any answer", () => {
    expect(stepStates(st({ done: 2 }))[2]).toBe("current");
    expect(stepStates(null)[0]).toBe("current");
  });
  it("ready is all done; failed marks the stuck step", () => {
    expect(stepStates(st({ state: "ready" })).every((x) => x === "done")).toBe(true);
    expect(stepStates(st({ state: "failed", step: "contacts" }))[3]).toBe("failed");
  });
  it("progress only comes from the server", () => {
    expect(progressOf(null)).toBe(0);
    expect(progressOf(st({ done: 2 }))).toBe(0.25);
    expect(progressOf(st({ state: "ready" }))).toBe(1);
  });
});

describe("sampleTargets", () => {
  const mask = (w: number, h: number, on: (x: number, y: number) => boolean) =>
    Array.from({ length: w * h }, (_, i) => (on(i % w, Math.floor(i / w)) ? 255 : 0));
  it("finds filled cells, sorted left to right", () => {
    const a = mask(20, 10, (x) => x >= 10);
    const pts = sampleTargets(a, 20, 10, 5, 100);
    expect(pts.length).toBe(4); // 2 columns x 2 rows of 5 px cells
    expect(pts[0]?.x).toBe(12.5);
    expect(pts.map((p) => p.x)).toEqual([...pts.map((p) => p.x)].sort((p, q) => p - q));
  });
  it("is empty for an empty mask and thins above max", () => {
    expect(sampleTargets(mask(10, 10, () => false), 10, 10, 2, 50)).toEqual([]);
    expect(sampleTargets(mask(40, 40, () => true), 40, 40, 2, 30)).toHaveLength(30);
  });
  it("reads alpha from RGBA", () => {
    expect(alphaChannel([0, 0, 0, 255, 1, 1, 1, 7])).toEqual([255, 7]);
  });
});

describe("refreshUntil", () => {
  const sleep = vi.fn(async () => {});
  it("retries until found", async () => {
    const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValueOnce(["a"]);
    const r = await refreshUntil(load, (l: string[]) => l.includes("a"), { sleep });
    expect(r).toEqual({ value: ["a"], ok: true });
    expect(load).toHaveBeenCalledTimes(2);
  });
  it("gives up with ok=false, survives one failed call, throws the last failure", async () => {
    const r = await refreshUntil(vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue([]), (l: string[]) => l.length > 0, { tries: 3, sleep });
    expect(r.ok).toBe(false);
    await expect(refreshUntil(() => Promise.reject(new Error("down")), () => true, { tries: 2, sleep })).rejects.toThrow("down");
  });
});
