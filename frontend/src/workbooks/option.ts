// Pure: visualization spec + query result -> ECharts option. No echarts import, no DOM, so the
// mapping is unit-testable. Every number is the query's value, printed exactly.
import { dimensionsOf, measureName, measuresOf } from "./spec";
import type { ColumnInfo, Visualization } from "./types";

export interface Palette {
  primary: string; series: string[]; ink: string; inkSoft: string; hairline: string; surface: string; font: string;
}
export interface Result { columns: ColumnInfo[]; rows: unknown[][] }
export type Option = Record<string, unknown>;
export type Raw = string | number | boolean | null;

const NF = new Intl.NumberFormat("en-US", { maximumFractionDigits: 12 });
/** The number exactly as the query returned it (thousands separators, no rounding). */
export function exact(v: unknown): string {
  if (v === null || v === undefined) return "-";
  return typeof v === "number" ? NF.format(v) : String(v);
}
export function labelOf(v: unknown): string { return v === null || v === undefined ? "(none)" : String(v); }

const idx = (r: Result, name: string) => r.columns.findIndex((c) => c.name === name);
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

function base(p: Palette): Option {
  return {
    color: p.series, backgroundColor: "transparent",
    textStyle: { fontFamily: p.font, color: p.ink },
    animation: false,
  };
}
function axis(p: Palette, extra: Option = {}): Option {
  return {
    axisLabel: { color: p.inkSoft, fontFamily: p.font, hideOverlap: true },
    axisLine: { lineStyle: { color: p.hairline } },
    axisTick: { lineStyle: { color: p.hairline } },
    splitLine: { lineStyle: { color: p.hairline } },
    nameTextStyle: { color: p.inkSoft, fontFamily: p.font },
    ...extra,
  };
}
const legend = (p: Palette, show: boolean): Option => ({
  show, bottom: 0, type: "scroll", textStyle: { color: p.inkSoft, fontFamily: p.font },
  pageTextStyle: { color: p.inkSoft, fontFamily: p.font }, pageIconColor: p.inkSoft, pageIconInactiveColor: p.hairline,
});
// richText: tooltips are drawn as canvas text, never HTML, so a name like "<img onerror=…>"
// from the data shows as itself (ECharts renders string tooltips as HTML by default).
const tooltip = (p: Palette, trigger: "axis" | "item", extra: Option = {}): Option => ({
  trigger, renderMode: "richText", valueFormatter: (v: unknown) => exact(v), confine: true,
  backgroundColor: p.surface, borderColor: p.hairline, textStyle: { color: p.ink, fontFamily: p.font },
  ...extra,
});

/** Labels of a category column, in query order, with their raw values. */
export function categories(res: Result, column: string): { labels: string[]; raws: Raw[] } {
  const i = idx(res, column);
  const labels: string[] = [], raws: Raw[] = [], seen = new Set<string>();
  for (const r of res.rows) {
    const l = labelOf(r[i]);
    if (seen.has(l)) continue;
    seen.add(l); labels.push(l); raws.push((r[i] ?? null) as Raw);
  }
  return { labels, raws };
}

/** ECharts option for the chart types; null for KPI, table and pivot (drawn as HTML). */
export function buildOption(v: Visualization, res: Result, p: Palette): Option | null {
  const dims = dimensionsOf(v), ms = measuresOf(v), mNames = ms.map(measureName);
  const o = v.options;
  switch (v.type) {
    case "bar": case "line": case "area": return cartesian(v, res, p, dims, mNames);
    case "pie": case "donut": {
      const ci = idx(res, dims[0] ?? ""), mi = idx(res, mNames[0] ?? "");
      return {
        ...base(p), tooltip: tooltip(p, "item"), legend: legend(p, true),
        series: [{
          type: "pie", name: mNames[0], radius: v.type === "donut" ? ["45%", "70%"] : "70%",
          center: ["50%", "45%"], label: { color: p.ink, fontFamily: p.font, show: o.show_labels, formatter: (q: { name: string; value: unknown }) => `${q.name}: ${exact(q.value)}` },
          itemStyle: { borderColor: p.surface, borderWidth: 2 },
          data: res.rows.map((r) => ({ name: labelOf(r[ci]), value: num(r[mi]) })),
        }],
      };
    }
    case "funnel": {
      const ci = idx(res, dims[0] ?? ""), mi = idx(res, mNames[0] ?? "");
      return {
        ...base(p), tooltip: tooltip(p, "item"), legend: legend(p, false),
        series: [{
          type: "funnel", sort: "descending", left: "8%", width: "84%", top: 8, bottom: 8,
          label: { show: true, position: "inside", color: p.surface, fontFamily: p.font, formatter: (q: { name: string; value: unknown }) => `${q.name}: ${exact(q.value)}` },
          itemStyle: { borderColor: p.surface, borderWidth: 1 },
          data: res.rows.map((r) => ({ name: labelOf(r[ci]), value: num(r[mi]) })),
        }],
      };
    }
    case "treemap": {
      const ci = idx(res, dims[0] ?? ""), mi = idx(res, mNames[0] ?? "");
      return {
        ...base(p), tooltip: tooltip(p, "item"),
        series: [{
          type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, width: "100%", height: "100%",
          label: { show: true, color: p.surface, fontFamily: p.font, formatter: (q: { name: string; value: unknown }) => `${q.name}\n${exact(q.value)}` },
          itemStyle: { borderColor: p.surface, borderWidth: 2, gapWidth: 2 },
          data: res.rows.filter((r) => (num(r[mi]) ?? 0) > 0).map((r) => ({ name: labelOf(r[ci]), value: num(r[mi]) })),
        }],
      };
    }
    case "heatmap": {
      const yi = idx(res, dims[0] ?? ""), xi = idx(res, dims[1] ?? ""), mi = idx(res, mNames[0] ?? "");
      const ys = categories(res, dims[0] ?? "").labels, xs = categories(res, dims[1] ?? "").labels;
      const data = res.rows.map((r) => [xs.indexOf(labelOf(r[xi])), ys.indexOf(labelOf(r[yi])), num(r[mi])]);
      const vals = data.map((d) => d[2]).filter((x): x is number => x !== null);
      return {
        ...base(p), tooltip: tooltip(p, "item", { formatter: (q: { value: unknown[] }) => `${xs[q.value[0] as number]} / ${ys[q.value[1] as number]}: ${exact(q.value[2])}` }),
        grid: { left: 8, right: 16, top: 8, bottom: 56, containLabel: true },
        xAxis: { type: "category", data: xs, ...axis(p, { splitArea: { show: false } }) },
        yAxis: { type: "category", data: ys, ...axis(p) },
        visualMap: {
          min: vals.length ? Math.min(...vals) : 0, max: vals.length ? Math.max(...vals) : 1, calculable: false,
          orient: "horizontal", left: "center", bottom: 4, inRange: { color: [p.hairline, p.primary] },
          textStyle: { color: p.inkSoft, fontFamily: p.font }, formatter: (x: number) => exact(x),
        },
        series: [{
          type: "heatmap", name: mNames[0], data,
          label: { show: o.show_labels, color: p.ink, fontFamily: p.font, formatter: (q: { value: unknown[] }) => exact(q.value[2]) },
          itemStyle: { borderColor: p.surface, borderWidth: 1 },
        }],
      };
    }
    case "scatter": return scatter(v, res, p, dims, mNames);
    default: return null;
  }
}

function cartesian(v: Visualization, res: Result, p: Palette, dims: string[], mNames: string[]): Option {
  const o = v.options, kind = v.type === "bar" ? "bar" : "line";
  const catCol = dims[0] ?? "", colorCol = dims[1];
  const ci = idx(res, catCol);
  const { labels } = categories(res, catCol);
  let series: Option[];
  if (colorCol) {
    const ki = idx(res, colorCol), mi = idx(res, mNames[0] ?? "");
    const groups = categories(res, colorCol).labels;
    series = groups.map((g) => ({
      name: g,
      data: labels.map((l) => {
        const row = res.rows.find((r) => labelOf(r[ci]) === l && labelOf(r[ki]) === g);
        return row ? num(row[mi]) : null;
      }),
    }));
  } else {
    series = mNames.map((n) => {
      const mi = idx(res, n);
      return { name: n, data: labels.map((l) => num(res.rows.find((r) => labelOf(r[ci]) === l)?.[mi])) };
    });
  }
  series = series.map((s) => ({
    ...s, type: kind, stack: o.stacked ? "total" : undefined,
    smooth: kind === "line" && o.smooth, showSymbol: kind === "line" ? labels.length < 60 : undefined,
    ...(v.type === "area" ? { areaStyle: { opacity: 0.25 } } : {}),
    label: { show: o.show_labels, color: p.ink, fontFamily: p.font, formatter: (q: { value: unknown }) => exact(q.value) },
    emphasis: { focus: "series" },
  }));
  const horiz = o.horizontal && v.type === "bar";
  const long = labels.some((l) => l.length > 10);
  const rotate = !horiz && (labels.length > 4 || long) ? 30 : 0;
  const catAxis = {
    type: "category", data: labels,
    ...axis(p, {
      splitLine: { show: false },
      axisLabel: {
        color: p.inkSoft, fontFamily: p.font, interval: 0, hideOverlap: false, rotate,
        width: horiz ? 90 : 80, overflow: "truncate", ellipsis: "…",
      },
    }),
  };
  const valAxis = { type: "value", ...axis(p) };
  return {
    ...base(p), tooltip: tooltip(p, "axis"), legend: legend(p, series.length > 1),
    grid: { left: 8, right: 16, top: 16, bottom: series.length > 1 ? 36 : 8, containLabel: true },
    xAxis: o.horizontal && v.type === "bar" ? valAxis : catAxis,
    yAxis: o.horizontal && v.type === "bar" ? { ...catAxis, inverse: true } : valAxis,
    series,
  };
}

function scatter(v: Visualization, res: Result, p: Palette, dims: string[], mNames: string[]): Option {
  const xi = idx(res, mNames[0] ?? ""), yi = idx(res, mNames[1] ?? ""), si = v.slots.size ? idx(res, mNames[2] ?? "") : -1;
  const li = idx(res, dims[0] ?? ""), ki = dims[1] ? idx(res, dims[1]) : -1;
  const sizes = si >= 0 ? res.rows.map((r) => num(r[si])).filter((x): x is number => x !== null) : [];
  const max = sizes.length ? Math.max(...sizes) : 0;
  const px = (raw: number | null) => (si < 0 || raw === null || max <= 0 ? 10 : 8 + 24 * Math.sqrt(Math.max(raw, 0) / max));
  const point = (r: unknown[]) => [num(r[xi]), num(r[yi]), si >= 0 ? num(r[si]) : null, labelOf(r[li]), px(si >= 0 ? num(r[si]) : null)];
  const groups = ki >= 0 ? categories(res, dims[1] ?? "").labels : [null];
  const series = groups.map((g) => ({
    type: "scatter", name: g ?? mNames[1], symbolSize: (d: unknown[]) => d[4],
    data: res.rows.filter((r) => g === null || labelOf(r[ki]) === g).map(point), emphasis: { focus: "series" },
  }));
  return {
    ...base(p),
    tooltip: tooltip(p, "item", {
      formatter: (q: { data: unknown[] }) =>
        `${q.data[3]}\n${mNames[0]}: ${exact(q.data[0])}\n${mNames[1]}: ${exact(q.data[1])}` + (si >= 0 ? `\n${mNames[2]}: ${exact(q.data[2])}` : ""),
    }),
    legend: legend(p, groups.length > 1),
    grid: { left: 8, right: 16, top: 16, bottom: groups.length > 1 ? 36 : 8, containLabel: true },
    xAxis: { type: "value", name: mNames[0], nameLocation: "middle", nameGap: 28, ...axis(p) },
    yAxis: { type: "value", name: mNames[1], ...axis(p) },
    series,
  };
}

// --- click -> cross-filter ------------------------------------------------------------------
export interface Pick { column: string; value: Raw; label: string }
export interface ChartEvent { name?: string; value?: unknown; data?: unknown }

/** What a click on a mark filters the other visualizations by (null: nothing to filter). */
export function pickFromEvent(v: Visualization, res: Result, ev: ChartEvent): Pick | null {
  const dims = dimensionsOf(v);
  const find = (col: string | undefined, label: string | undefined): Pick | null => {
    if (!col || label === undefined) return null;
    const { labels, raws } = categories(res, col);
    const i = labels.indexOf(label);
    return i < 0 ? null : { column: col, value: raws[i] as Raw, label };
  };
  switch (v.type) {
    case "bar": case "line": case "area": case "pie": case "donut": case "funnel": case "treemap":
      return find(dims[0], ev.name);
    case "heatmap": {
      const val = ev.value as unknown[] | undefined;
      if (!Array.isArray(val)) return null;
      const xs = categories(res, dims[1] ?? "").labels;
      return find(dims[1], xs[val[0] as number]);
    }
    case "scatter": return Array.isArray(ev.data) ? find(dims[0], String(ev.data[3])) : null;
    default: return null;
  }
}

// --- HTML visualizations -----------------------------------------------------------------------
export function kpiOf(v: Visualization, res: Result): { label: string; value: string } {
  const m = measuresOf(v)[0];
  const name = m ? measureName(m) : "";
  const i = idx(res, name);
  return { label: v.title || name, value: exact(res.rows[0]?.[i]) };
}

export interface Pivot {
  rowHeads: string[]; colHeads: string[]; rowKeys: string[][]; colKeys: string[][];
  cell: (r: number, c: number, m: number) => unknown; measures: string[];
}

/** Cross-tab of the query's rows. Cells are the query's values; nothing is summed or averaged here. */
export function buildPivot(v: Visualization, res: Result): Pivot {
  const rowsC = v.slots.rows, colsC = v.slots.columns, measures = measuresOf(v).map(measureName);
  const ri = rowsC.map((c) => idx(res, c)), ci = colsC.map((c) => idx(res, c)), mi = measures.map((n) => idx(res, n));
  const key = (r: unknown[], ix: number[]) => ix.map((i) => labelOf(r[i]));
  const uniq = (ix: number[]) => {
    const m = new Map<string, string[]>();
    for (const r of res.rows) { const k = key(r, ix); m.set(JSON.stringify(k), k); }
    return [...m.values()];
  };
  const rowKeys = uniq(ri), colKeys = ci.length ? uniq(ci) : [[]];
  const cells = new Map<string, unknown[]>();
  for (const r of res.rows) cells.set(JSON.stringify([key(r, ri), key(r, ci)]), mi.map((i) => r[i]));
  return {
    rowHeads: rowsC, colHeads: colsC, rowKeys, colKeys, measures,
    cell: (r, c, m) => cells.get(JSON.stringify([rowKeys[r], colKeys[c]]))?.[m],
  };
}
