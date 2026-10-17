import { describe, expect, it } from "vitest";
import { asNum, fmtCell, isTotalColumn, niceScale, pivotModel, project } from "./pivot";
import type { PivotView } from "./types";

const view: PivotView = {
  kind: "pivot", row_headers: ["segment"], column_values: ["won", "lost", "Total"], truncated_columns: 2,
  rows: [{ keys: ["SMB"], cells: [3, 1, 4] }, { keys: ["Total"], cells: [3, 1, 4] }],
};

describe("pivot helpers", () => {
  it("marks the totals row and column", () => {
    const m = pivotModel(view);
    expect(m.rows.map((r) => r.isTotal)).toEqual([false, true]);
    expect(isTotalColumn(m, 2)).toBe(true);
    expect(isTotalColumn(m, 0)).toBe(false);
    expect(m.truncatedColumns).toBe(2);
  });
  it("does not treat a data row named Total as totals unless last", () => {
    const m = pivotModel({ ...view, rows: [{ keys: ["Total"], cells: [1, 1, 2] }, { keys: ["B"], cells: [1, 1, 2] }] });
    expect(m.rows[0]!.isTotal).toBe(false);
  });
  it("formats cells as plain text", () => {
    expect(fmtCell(null)).toBe("");
    expect(fmtCell(1234567)).toBe("1,234,567");
    expect(fmtCell(0.12345)).toBe("0.12");
    expect(fmtCell(NaN)).toBe("");
    expect(fmtCell("<b>x</b>")).toBe("<b>x</b>");
    expect(fmtCell(true)).toBe("true");
  });
});

describe("chart scales", () => {
  it("makes nice ticks", () => {
    const s = niceScale(0, 97);
    expect(s.min).toBe(0);
    expect(s.max).toBeGreaterThanOrEqual(97);
    expect(s.ticks[0]).toBe(0);
  });
  it("handles flat and invalid ranges", () => {
    expect(niceScale(5, 5).max).toBeGreaterThan(5);
    expect(niceScale(NaN, 1).ticks).toEqual([0, 1]);
  });
  it("projects and parses numbers", () => {
    expect(project(5, { min: 0, max: 10, ticks: [] }, 100)).toBe(50);
    expect(asNum("3.5")).toBe(3.5);
    expect(asNum("")).toBeNull();
    expect(asNum(null)).toBeNull();
  });
});
