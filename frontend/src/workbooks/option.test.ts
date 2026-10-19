import { describe, expect, it } from "vitest";
import { buildOption, buildPivot, categories, exact, kpiOf, pickFromEvent, type Palette, type Result } from "./option";
import { newViz, addField } from "./spec";
import type { Visualization, VizType } from "./types";

const pal: Palette = {
  primary: "P", series: ["s1", "s2", "s3"], ink: "I", inkSoft: "IS", hairline: "H", surface: "S", font: "Helvetica",
};
const src = { kind: "crm", table: "deals" } as const;
const mk = (type: VizType, fill: (v: Visualization) => Visualization): Visualization =>
  fill(newViz("v1", type, src));
const f = (name: string, dtype: "text" | "number" = "text") => ({ name, dtype });

const res: Result = {
  columns: [
    { name: "stage", dtype: "text" }, { name: "segment", dtype: "text" },
    { name: "sum(amount_eur)", dtype: "number" }, { name: "count", dtype: "integer" },
  ],
  rows: [
    ["won", "smb", 1000.5, 3], ["won", "ent", 5000, 2], ["lost", "smb", 700, 4], [null, "ent", 10, 1],
  ],
};
const two: Result = { columns: res.columns, rows: res.rows.slice(0, 2).map((r) => [r[0], r[1], r[2], r[3]]) };

describe("exact", () => {
  it("prints the value without rounding", () => {
    expect(exact(1234567.891)).toBe("1,234,567.891");
    expect(exact(0.1 + 0.2)).toBe("0.3");
    expect(exact(null)).toBe("-");
  });
});

describe("bar / line / area", () => {
  const bar = mk("bar", (v) => addField(addField(v, f("stage")), f("amount_eur", "number")));
  const r1: Result = { columns: [res.columns[0]!, res.columns[2]!], rows: [["won", 1000.5], ["lost", 700], [null, 10]] };
  it("one series per measure, exact data, null category labelled", () => {
    const o = buildOption(bar, r1, pal) as any;
    expect(o.xAxis.data).toEqual(["won", "lost", "(none)"]);
    expect(o.series).toHaveLength(1);
    expect(o.series[0].type).toBe("bar");
    expect(o.series[0].data).toEqual([1000.5, 700, 10]);
    expect(o.series[0].name).toBe("sum(amount_eur)");
    expect(o.legend.show).toBe(false);
    expect(o.color).toEqual(pal.series);
    expect(o.textStyle.fontFamily).toBe("Helvetica");
  });
  it("stacked and horizontal", () => {
    const v = { ...bar, options: { ...bar.options, stacked: true, horizontal: true } };
    const o = buildOption(v, r1, pal) as any;
    expect(o.series[0].stack).toBe("total");
    expect(o.yAxis.type).toBe("category");
    expect(o.xAxis.type).toBe("value");
  });
  it("color slot pivots to series, missing cells stay null", () => {
    const v = addField(bar, f("segment"));
    expect(v.slots.color).toBe("segment");
    const o = buildOption(v, { columns: res.columns, rows: res.rows.slice(0, 3) }, pal) as any;
    expect(o.series.map((s: any) => s.name)).toEqual(["smb", "ent"]);
    expect(o.series[0].data).toEqual([1000.5, 700]);
    expect(o.series[1].data).toEqual([5000, null]);
    expect(o.legend.show).toBe(true);
  });
  it("line smooth and area fill", () => {
    const line = { ...bar, type: "line" as const, options: { ...bar.options, smooth: true } };
    expect((buildOption(line, r1, pal) as any).series[0]).toMatchObject({ type: "line", smooth: true });
    const area = { ...bar, type: "area" as const };
    const s = (buildOption(area, r1, pal) as any).series[0];
    expect(s.type).toBe("line");
    expect(s.areaStyle).toBeDefined();
  });
});

describe("pie, donut, funnel, treemap", () => {
  const r: Result = { columns: [res.columns[0]!, res.columns[3]!], rows: [["won", 5], ["lost", 4]] };
  const mkc = (t: VizType) => mk(t, (v) => addField(addField(v, f("stage")), f("*", "text")));
  it("pie", () => {
    const o = buildOption(mkc("pie"), r, pal) as any;
    expect(o.series[0].type).toBe("pie");
    expect(o.series[0].radius).toBe("70%");
    expect(o.series[0].data).toEqual([{ name: "won", value: 5 }, { name: "lost", value: 4 }]);
  });
  it("donut has an inner radius", () => {
    expect((buildOption(mkc("donut"), r, pal) as any).series[0].radius).toEqual(["45%", "70%"]);
  });
  it("funnel", () => {
    const s = (buildOption(mkc("funnel"), r, pal) as any).series[0];
    expect(s.type).toBe("funnel");
    expect(s.data[0]).toEqual({ name: "won", value: 5 });
  });
  it("treemap drops non-positive tiles", () => {
    const rr: Result = { ...r, rows: [["won", 5], ["lost", 0]] };
    const s = (buildOption(mkc("treemap"), rr, pal) as any).series[0];
    expect(s.type).toBe("treemap");
    expect(s.data).toEqual([{ name: "won", value: 5 }]);
  });
});

describe("heatmap", () => {
  const v = mk("heatmap", (x) => addField(addField(addField(x, f("segment")), f("stage")), f("*", "text")));
  it("rows x columns grid with visualMap bounds", () => {
    expect(v.slots.rows).toEqual(["segment"]);
    expect(v.slots.columns).toEqual(["stage"]);
    const r: Result = {
      columns: [res.columns[1]!, res.columns[0]!, res.columns[3]!],
      rows: [["smb", "won", 3], ["ent", "won", 2], ["smb", "lost", 4]],
    };
    const o = buildOption(v, r, pal) as any;
    expect(o.xAxis.data).toEqual(["won", "lost"]);
    expect(o.yAxis.data).toEqual(["smb", "ent"]);
    expect(o.series[0].data).toEqual([[0, 0, 3], [0, 1, 2], [1, 0, 4]]);
    expect(o.visualMap).toMatchObject({ min: 2, max: 4 });
    expect(o.visualMap.inRange.color).toEqual([pal.hairline, pal.primary]);
  });
});

describe("scatter", () => {
  const v = mk("scatter", (x) =>
    addField(addField(addField(addField(x, f("segment")), f("amount_eur", "number")), f("count", "number")), f("n", "number"), "size"),
  );
  it("x, y, size and label per point", () => {
    expect(v.slots.values.map((m) => m.column)).toEqual(["amount_eur", "count"]);
    const r: Result = {
      columns: [{ name: "segment", dtype: "text" }, { name: "sum(amount_eur)", dtype: "number" }, { name: "sum(count)", dtype: "number" }, { name: "sum(n)", dtype: "number" }],
      rows: [["smb", 10, 2, 100], ["ent", 20, 4, 25]],
    };
    const o = buildOption(v, r, pal) as any;
    expect(o.series).toHaveLength(1);
    expect(o.series[0].type).toBe("scatter");
    expect(o.series[0].data[0].slice(0, 4)).toEqual([10, 2, 100, "smb"]);
    expect(o.series[0].data[0][4]).toBeCloseTo(32);
    expect(o.series[0].data[1][4]).toBeCloseTo(8 + 24 * 0.5);
    expect(o.xAxis.name).toBe("sum(amount_eur)");
  });
  it("tooltips are plain text, never HTML", () => {
    const r: Result = {
      columns: [{ name: "segment", dtype: "text" }, { name: "sum(amount_eur)", dtype: "number" }, { name: "sum(count)", dtype: "number" }, { name: "sum(n)", dtype: "number" }],
      rows: [["<img src=x onerror=alert(1)>", 10, 2, 100]],
    };
    const o = buildOption(v, r, pal) as any;
    expect(o.tooltip.renderMode).toBe("richText");
    const text = o.tooltip.formatter({ data: o.series[0].data[0] });
    expect(text).not.toContain("<br");
    expect(text.split("\n")[0]).toBe("<img src=x onerror=alert(1)>");
  });
});

describe("html visualizations", () => {
  it("kpi shows the exact value", () => {
    const v = mk("kpi", (x) => addField(x, f("amount_eur", "number")));
    const r: Result = { columns: [{ name: "sum(amount_eur)", dtype: "number" }], rows: [[1234567.25]] };
    expect(buildOption(v, r, pal)).toBeNull();
    expect(kpiOf(v, r)).toEqual({ label: "sum(amount_eur)", value: "1,234,567.25" });
    expect(kpiOf({ ...v, title: "Pipeline" }, r).label).toBe("Pipeline");
  });
  it("pivot keeps the query's cells", () => {
    const v = mk("pivot", (x) => addField(addField(addField(x, f("segment")), f("stage"), "columns"), f("*", "text")));
    const r: Result = {
      columns: [res.columns[1]!, res.columns[0]!, res.columns[3]!],
      rows: [["smb", "won", 3], ["smb", "lost", 4], ["ent", "won", 2]],
    };
    const p = buildPivot(v, r);
    expect(p.rowKeys).toEqual([["smb"], ["ent"]]);
    expect(p.colKeys).toEqual([["won"], ["lost"]]);
    expect(p.cell(0, 1, 0)).toBe(4);
    expect(p.cell(1, 1, 0)).toBeUndefined();
  });
  it("table and pivot are not echarts", () => {
    expect(buildOption(mk("table", (x) => addField(x, f("stage"))), res, pal)).toBeNull();
  });
});

describe("click -> pick", () => {
  const bar = mk("bar", (v) => addField(addField(v, f("stage")), f("amount_eur", "number")));
  const r: Result = { columns: [res.columns[0]!, res.columns[2]!], rows: [["won", 1], [null, 2]] };
  it("returns the raw value of the clicked category", () => {
    expect(pickFromEvent(bar, r, { name: "won" })).toEqual({ column: "stage", value: "won", label: "won" });
    expect(pickFromEvent(bar, r, { name: "(none)" })).toEqual({ column: "stage", value: null, label: "(none)" });
    expect(pickFromEvent(bar, r, { name: "zzz" })).toBeNull();
  });
  it("heatmap and scatter", () => {
    const h = mk("heatmap", (x) => addField(addField(addField(x, f("segment")), f("stage")), f("*", "text")));
    const hr: Result = { columns: [res.columns[1]!, res.columns[0]!, res.columns[3]!], rows: [["smb", "won", 3], ["smb", "lost", 4]] };
    expect(pickFromEvent(h, hr, { value: [1, 0, 4] })).toMatchObject({ column: "stage", value: "lost" });
    const s = mk("scatter", (x) => addField(addField(addField(x, f("segment")), f("a", "number")), f("b", "number")));
    const sr: Result = { columns: [res.columns[1]!, res.columns[2]!, res.columns[3]!], rows: [["ent", 1, 2]] };
    expect(pickFromEvent(s, sr, { data: [1, 2, null, "ent", 10] })).toMatchObject({ column: "segment", value: "ent" });
    expect(pickFromEvent(mk("kpi", (x) => x), sr, { name: "x" })).toBeNull();
  });
  it("categories keeps first-seen order", () => {
    expect(categories(two, "stage").labels).toEqual(["won"]);
  });
});
