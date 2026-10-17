import type { PivotView } from "./types";

/** Text for any cell value (server text is rendered as text, never as HTML). */
export function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "";
    return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export const TOTAL_LABEL = "Total";

export interface PivotRowModel { keys: string[]; cells: string[]; isTotal: boolean }
export interface PivotModel {
  headers: string[]; columns: string[]; rows: PivotRowModel[]; truncatedColumns: number; hasTotalColumn: boolean;
}

/** Turn a PivotView into display strings; the totals row is the one whose first key is "Total". */
export function pivotModel(v: PivotView): PivotModel {
  const hasTotalColumn = v.column_values[v.column_values.length - 1] === TOTAL_LABEL;
  const rows = v.rows.map((r, i) => {
    const keys = r.keys.map(fmtCell);
    const last = i === v.rows.length - 1;
    return { keys, cells: r.cells.map(fmtCell), isTotal: last && keys[0] === TOTAL_LABEL };
  });
  return { headers: v.row_headers, columns: v.column_values, rows, truncatedColumns: v.truncated_columns, hasTotalColumn };
}

/** Is column index i the totals column? */
export const isTotalColumn = (m: PivotModel, i: number): boolean => m.hasTotalColumn && i === m.columns.length - 1;

// ---- chart helpers (pure, so they are testable) ----
export interface Scale { min: number; max: number; ticks: number[] }
export function niceScale(min: number, max: number, n = 5): Scale {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1, ticks: [0, 1] };
  if (min === max) { max = min + 1; if (min === 0) min = 0; }
  const span = max - min;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw)) as number;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Math.round(t / step) * step);
  return { min: lo, max: hi, ticks };
}
export function project(v: number, s: Scale, size: number): number {
  return s.max === s.min ? 0 : ((v - s.min) / (s.max - s.min)) * size;
}
export const asNum = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};
