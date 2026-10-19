import { describe, expect, it } from "vitest";
import {
  addField, autoSlot, buildQuery, changeType, crossFiltersFor, defaultAgg, emptySlots, isComplete, missingSlots,
  moveItem, newViz, nextVizId, orderedLayout, packLayout, reduceCross, removeFromSlot, resizeItem, roleOf,
  selectedValue, setAgg, autoTitle, displayTitle, type CrossFilter,
} from "./spec";
import type { Dtype, VizType } from "./types";

const src = { kind: "crm", table: "deals" } as const;
const text = (name: string) => ({ name, dtype: "text" as Dtype });
const numf = (name: string) => ({ name, dtype: "number" as Dtype });
const viz = (t: VizType) => newViz("v1", t, src);

describe("field roles", () => {
  it("numbers are measures, the rest dimensions", () => {
    expect(roleOf("number")).toBe("measure");
    expect(roleOf("integer")).toBe("measure");
    for (const d of ["text", "boolean", "date", "datetime"] as Dtype[]) expect(roleOf(d)).toBe("dimension");
  });
  it("default aggregate", () => {
    expect(defaultAgg(numf("amount_eur"))).toBe("sum");
    expect(defaultAgg(text("stage"))).toBe("count");
    expect(defaultAgg({ name: "*", dtype: "integer" })).toBe("count");
  });
});

describe("slots", () => {
  it("auto-slots by role", () => {
    const v = viz("bar");
    expect(autoSlot("bar", v.slots, text("stage"))).toBe("category");
    expect(autoSlot("bar", v.slots, numf("amount"))).toBe("values");
    const withCat = addField(v, text("stage"));
    expect(autoSlot("bar", withCat.slots, text("segment"))).toBe("color");
    const full = addField(withCat, text("segment"));
    expect(autoSlot("bar", full.slots, text("owner"))).toBe("category"); // replaces
  });
  it("adds, dedups and caps measures", () => {
    let v = addField(viz("bar"), numf("a"));
    expect(v.slots.values).toEqual([{ column: "a", agg: "sum" }]);
    expect(addField(v, numf("a"))).toBe(v);
    for (let i = 0; i < 12; i++) v = addField(v, numf(`m${i}`));
    expect(v.slots.values).toHaveLength(8);
  });
  it("single-value slots replace", () => {
    let v = addField(viz("pie"), numf("a"));
    v = addField(v, numf("b"));
    expect(v.slots.values).toEqual([{ column: "b", agg: "sum" }]);
  });
  it("'*' only goes to a measure slot", () => {
    const star = { name: "*", dtype: "integer" as Dtype };
    expect(addField(viz("bar"), star, "category").slots.category).toBeNull();
    expect(addField(viz("bar"), star).slots.values).toEqual([{ column: "*", agg: "count" }]);
    expect(setAgg(addField(viz("bar"), star), "values", 0, "sum").slots.values[0]!.agg).toBe("count");
  });
  it("explicit slot, remove and setAgg", () => {
    let v = addField(viz("table"), text("stage"), "rows");
    v = addField(v, numf("amount"));
    v = setAgg(v, "values", 0, "median");
    expect(v.slots.values[0]).toEqual({ column: "amount", agg: "median" });
    v = removeFromSlot(v, "rows", 0);
    expect(v.slots.rows).toEqual([]);
    expect(removeFromSlot(addField(viz("bar"), text("s")), "category").slots.category).toBeNull();
  });
  it("completeness per type", () => {
    expect(missingSlots(viz("bar"))).toEqual(["Category", "Values"]);
    expect(isComplete(addField(addField(viz("bar"), text("s")), numf("a")))).toBe(true);
    expect(isComplete(addField(viz("kpi"), numf("a")))).toBe(true);
    expect(isComplete(viz("table"))).toBe(false);
    expect(isComplete(addField(viz("table"), text("s")))).toBe(true);
    const sc = addField(addField(viz("scatter"), text("p")), numf("x"));
    expect(isComplete(sc)).toBe(false);
    expect(isComplete(addField(sc, numf("y")))).toBe(true);
  });
  it("changing type keeps the fields that fit and the chosen aggregate", () => {
    let v = addField(addField(viz("bar"), text("stage")), numf("amount"));
    v = setAgg(v, "values", 0, "mean");
    const dt = new Map<string, Dtype>([["stage", "text"], ["amount", "number"]]);
    const pie = changeType(v, "pie", dt);
    expect(pie.slots.category).toBe("stage");
    expect(pie.slots.values).toEqual([{ column: "amount", agg: "mean" }]);
    const heat = changeType(v, "heatmap", dt);
    expect(heat.slots.rows).toEqual(["stage"]);
    expect(heat.slots.values[0]).toEqual({ column: "amount", agg: "mean" });
    expect(changeType(v, "bar", dt)).toBe(v);
  });
});

describe("buildQuery", () => {
  it("is null while incomplete", () => {
    expect(buildQuery(viz("bar"), [])).toBeNull();
  });
  it("bar: dimensions, measures, filters, limit", () => {
    const v = addField(addField(addField(viz("bar"), text("stage")), numf("amount")), text("segment"));
    const f = [{ column: "region", op: "eq" as const, value: "EU" }];
    const q = buildQuery(v, f)!;
    expect(q.dimensions).toEqual(["stage", "segment"]);
    expect(q.measures).toEqual([{ column: "amount", agg: "sum" }]);
    expect(q.filters).toEqual(f);
    expect(q.limit).toBe(200);
    expect(q.sort).toEqual([]);
  });
  it("line sorts by its category ascending; sort_by honoured when it is an output column", () => {
    const l = addField(addField(viz("line"), text("created_on")), numf("amount"));
    expect(buildQuery(l, [])!.sort).toEqual([{ by: "created_on", descending: false }]);
    const b = addField(addField(viz("bar"), text("stage")), numf("amount"));
    const bs = { ...b, options: { ...b.options, sort_by: "sum(amount)", descending: false } };
    expect(buildQuery(bs, [])!.sort).toEqual([{ by: "sum(amount)", descending: false }]);
    expect(buildQuery({ ...b, options: { ...b.options, sort_by: "nope" } }, [])!.sort).toEqual([]);
  });
  it("kpi has no dimension and limit 1; pivot groups by rows then columns", () => {
    const k = addField(viz("kpi"), numf("amount"));
    expect(buildQuery(k, [])).toMatchObject({ dimensions: [], limit: 1 });
    let p = addField(viz("pivot"), text("segment"));
    p = addField(p, text("stage"), "columns");
    p = addField(p, numf("amount"));
    expect(buildQuery(p, [])!.dimensions).toEqual(["segment", "stage"]);
  });
  it("with a color slot only the first measure is queried", () => {
    let v = addField(addField(viz("bar"), text("stage")), numf("a"));
    v = addField(addField(v, numf("b")), text("segment"));
    expect(buildQuery(v, [])!.measures).toHaveLength(1);
  });
});

describe("cross-filter reducer", () => {
  const a: CrossFilter = { vizId: "v1", column: "stage", value: "won", label: "won" };
  const b: CrossFilter = { vizId: "v1", column: "stage", value: "lost", label: "lost" };
  const c: CrossFilter = { vizId: "v2", column: "segment", value: null, label: "(none)" };
  it("toggle adds, replaces the same viz's selection, and clears on a second click", () => {
    let s = reduceCross([], { type: "toggle", filter: a });
    expect(s).toEqual([a]);
    s = reduceCross(s, { type: "toggle", filter: b });
    expect(s).toEqual([b]);
    s = reduceCross(s, { type: "toggle", filter: c });
    expect(s).toEqual([b, c]);
    s = reduceCross(s, { type: "toggle", filter: b });
    expect(s).toEqual([c]);
  });
  it("remove, dropViz, clear", () => {
    const s = [a, c];
    expect(reduceCross(s, { type: "remove", vizId: "v1", column: "stage" })).toEqual([c]);
    expect(reduceCross(s, { type: "dropViz", vizId: "v2" })).toEqual([a]);
    expect(reduceCross(s, { type: "clear" })).toEqual([]);
  });
  it("a visualization never filters itself; unknown columns are skipped", () => {
    const s = [a, c];
    expect(crossFiltersFor(s, "v1", null)).toEqual([{ column: "segment", op: "is_null" }]);
    expect(crossFiltersFor(s, "v3", null)).toEqual([
      { column: "stage", op: "eq", value: "won" }, { column: "segment", op: "is_null" },
    ]);
    expect(crossFiltersFor(s, "v3", new Set(["stage"]))).toEqual([{ column: "stage", op: "eq", value: "won" }]);
    expect(selectedValue(s, "v2")).toBe(c);
    expect(selectedValue(s, "v9")).toBeUndefined();
  });
  it("does not mutate its input", () => {
    const s = Object.freeze([a]) as CrossFilter[];
    expect(() => reduceCross(s, { type: "toggle", filter: b })).not.toThrow();
  });
});

describe("layout", () => {
  it("packs left to right and wraps at 12 columns", () => {
    const l = packLayout([
      { viz_id: "a", w: 6, h: 4 }, { viz_id: "b", w: 6, h: 3 }, { viz_id: "c", w: 4, h: 2 }, { viz_id: "d", w: 12, h: 2 },
    ]);
    expect(l.map((i) => [i.viz_id, i.x, i.y])).toEqual([["a", 0, 0], ["b", 6, 0], ["c", 0, 4], ["d", 0, 6]]);
  });
  it("moves and resizes, keeping every tile", () => {
    const l = packLayout([{ viz_id: "a", w: 6, h: 4 }, { viz_id: "b", w: 6, h: 4 }, { viz_id: "c", w: 6, h: 4 }]);
    expect(moveItem(l, "c", "a").map((i) => i.viz_id)).toEqual(["c", "a", "b"]);
    expect(moveItem(l, "a", "a")).toBe(l);
    const r = resizeItem(l, "a", 12, 99);
    expect(r[0]).toMatchObject({ w: 12, h: 40 });
    expect(r[1]).toMatchObject({ x: 0, y: 40 });
  });
  it("orderedLayout appends missing tiles and drops orphans", () => {
    const v1 = newViz("v1", "bar", src), v2 = newViz("v2", "kpi", src);
    const o = orderedLayout({ layout: [{ viz_id: "ghost", x: 0, y: 0, w: 6, h: 4 }, { viz_id: "v1", x: 0, y: 0, w: 6, h: 4 }], visualizations: [v1, v2] });
    expect(o.map((i) => i.viz_id)).toEqual(["v1", "v2"]);
    expect(o[1]).toMatchObject({ w: 4, h: 2 });
  });
  it("nextVizId skips used ids", () => {
    expect(nextVizId({ visualizations: [newViz("v1", "bar", src), newViz("v3", "bar", src)] })).toBe("v2");
  });
  it("emptySlots is fresh each time", () => {
    expect(emptySlots()).not.toBe(emptySlots());
  });
});

describe("automatic title", () => {
  const src = newViz("v1", "bar", { kind: "flow_block", block_id: "", workspace: "" } as never);
  it("names measure and dimension", () => {
    const v = { ...src, slots: { ...emptySlots(), category: "stage", values: [{ column: "amount_eur", agg: "sum" as const }] } };
    expect(autoTitle(v)).toBe("Sum of amount_eur by stage");
    expect(autoTitle({ ...v, slots: { ...v.slots, values: [{ column: "*", agg: "count" as const }] } })).toBe("Number of rows by stage");
    expect(autoTitle({ ...v, type: "kpi", slots: { ...v.slots, category: null } })).toBe("Sum of amount_eur");
  });
  it("prefers the typed title and falls back to the type", () => {
    expect(displayTitle({ ...src, title: "Mine" })).toBe("Mine");
    expect(displayTitle(src)).toBe("Bar");
  });
});
