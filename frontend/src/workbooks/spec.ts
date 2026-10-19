// Pure logic of the workbook editor: slots, queries, cross-filtering and the grid layout.
import type {
  Agg, Canvas, ColumnInfo, Dtype, Filter, LayoutItem, Measure, QueryRequest, Source, Slots,
  Visualization, VizOptions, VizType,
} from "./types";

export const MAX_CANVASES = 12;
export const MAX_VIZ = 30;
export const GRID_COLS = 12;

export type SlotName = "category" | "values" | "color" | "size" | "rows" | "columns";
export interface SlotDef {
  slot: SlotName; label: string; kind: "dimension" | "measure";
  /** How many fields the slot holds. */
  max: number; required: boolean;
}

const dim = (slot: SlotName, label: string, max: number, required = false): SlotDef =>
  ({ slot, label, kind: "dimension", max, required });
const mea = (slot: SlotName, label: string, max: number, required = false): SlotDef =>
  ({ slot, label, kind: "measure", max, required });

export const SLOT_DEFS: Record<VizType, SlotDef[]> = {
  bar: [dim("category", "Category", 1, true), mea("values", "Values", 8, true), dim("color", "Color", 1)],
  line: [dim("category", "Category", 1, true), mea("values", "Values", 8, true), dim("color", "Color", 1)],
  area: [dim("category", "Category", 1, true), mea("values", "Values", 8, true), dim("color", "Color", 1)],
  scatter: [
    dim("category", "Point", 1, true), mea("values", "X, then Y", 2, true), mea("size", "Size", 1), dim("color", "Color", 1),
  ],
  pie: [dim("category", "Slices", 1, true), mea("values", "Value", 1, true)],
  donut: [dim("category", "Slices", 1, true), mea("values", "Value", 1, true)],
  funnel: [dim("category", "Stages", 1, true), mea("values", "Value", 1, true)],
  treemap: [dim("category", "Tiles", 1, true), mea("values", "Size", 1, true)],
  heatmap: [dim("rows", "Rows", 1, true), dim("columns", "Columns", 1, true), mea("values", "Value", 1, true)],
  kpi: [mea("values", "Value", 1, true)],
  table: [dim("rows", "Columns", 8), mea("values", "Measures", 8)],
  pivot: [dim("rows", "Rows", 3, true), dim("columns", "Columns", 3), mea("values", "Values", 4, true)],
};

export const VIZ_LABEL: Record<VizType, string> = {
  bar: "Bar", line: "Line", area: "Area", scatter: "Scatter", pie: "Pie", donut: "Donut",
  heatmap: "Heatmap", treemap: "Treemap", funnel: "Funnel", kpi: "KPI", table: "Table", pivot: "Pivot",
};
export const VIZ_TYPES = Object.keys(SLOT_DEFS) as VizType[];

export const STAR: FieldRef = { name: "*", dtype: "integer" };
export interface FieldRef { name: string; dtype: Dtype }

export function isNumeric(d: Dtype): boolean { return d === "number" || d === "integer"; }
/** Numbers are measures; text, booleans and dates are dimensions. */
export function roleOf(d: Dtype): "measure" | "dimension" { return isNumeric(d) ? "measure" : "dimension"; }
export function defaultAgg(f: FieldRef): Agg { return f.name === "*" ? "count" : isNumeric(f.dtype) ? "sum" : "count"; }
export function aggsFor(f: FieldRef): Agg[] {
  if (f.name === "*") return ["count"];
  return isNumeric(f.dtype)
    ? ["sum", "mean", "median", "min", "max", "count", "count_distinct"]
    : f.dtype === "boolean"
      ? ["sum", "mean", "count", "count_distinct"]
      : ["count", "count_distinct", "min", "max"];
}
export function measureName(m: Measure): string { return m.column === "*" ? "count" : `${m.agg}(${m.column})`; }

export const DEFAULT_OPTIONS: VizOptions = {
  stacked: false, smooth: false, show_labels: false, horizontal: false, limit: 200, sort_by: null, descending: true,
};
export function emptySlots(): Slots { return { category: null, values: [], color: null, size: null, rows: [], columns: [] }; }

export function newViz(id: string, type: VizType, source: Source): Visualization {
  return { id, type, title: "", source, slots: emptySlots(), options: { ...DEFAULT_OPTIONS } };
}

function slotCount(s: Slots, slot: SlotName): number {
  switch (slot) {
    case "category": return s.category ? 1 : 0;
    case "color": return s.color ? 1 : 0;
    case "size": return s.size ? 1 : 0;
    case "values": return s.values.length;
    case "rows": return s.rows.length;
    case "columns": return s.columns.length;
  }
}

/** The slot a clicked field goes to: the first slot of its role with room, else any with room. */
export function autoSlot(type: VizType, slots: Slots, f: FieldRef): SlotName | null {
  const defs = SLOT_DEFS[type];
  const wanted = f.name === "*" ? "measure" : roleOf(f.dtype);
  const room = (d: SlotDef) => slotCount(slots, d.slot) < d.max;
  const same = defs.find((d) => d.kind === wanted && room(d));
  if (same) return same.slot;
  if (f.name === "*") return null;
  // Single-field slots can be replaced: prefer the first of the role, then room elsewhere.
  const replaceable = defs.find((d) => d.kind === wanted && d.max === 1);
  if (replaceable) return replaceable.slot;
  return defs.find((d) => room(d))?.slot ?? null;
}

/** Returns a new visualization with `f` in `slot` (or the automatic slot); the same object if refused. */
export function addField(v: Visualization, f: FieldRef, slot?: SlotName): Visualization {
  const target = slot ?? autoSlot(v.type, v.slots, f);
  const def = SLOT_DEFS[v.type].find((d) => d.slot === target);
  if (!target || !def) return v;
  if (f.name === "*" && def.kind !== "measure") return v;
  const s: Slots = { ...v.slots, values: [...v.slots.values], rows: [...v.slots.rows], columns: [...v.slots.columns] };
  if (def.kind === "measure") {
    const m: Measure = { column: f.name, agg: defaultAgg(f) };
    if (target === "size") s.size = m;
    else {
      if (s.values.some((x) => x.column === m.column && x.agg === m.agg)) return v;
      if (def.max === 1) s.values = [m];
      else if (s.values.length >= def.max) return v;
      else s.values.push(m);
    }
  } else if (target === "category" || target === "color") {
    s[target] = f.name;
  } else if (target === "rows" || target === "columns") {
    const list = s[target];
    if (list.includes(f.name)) return v;
    if (def.max === 1) s[target] = [f.name];
    else if (list.length >= def.max) return v;
    else list.push(f.name);
  }
  return { ...v, slots: s };
}

export function removeFromSlot(v: Visualization, slot: SlotName, index = 0): Visualization {
  const s: Slots = { ...v.slots, values: [...v.slots.values], rows: [...v.slots.rows], columns: [...v.slots.columns] };
  if (slot === "category" || slot === "color") s[slot] = null;
  else if (slot === "size") s.size = null;
  else s[slot].splice(index, 1);
  return { ...v, slots: s };
}

export function setAgg(v: Visualization, slot: "values" | "size", index: number, agg: Agg): Visualization {
  if (slot === "size") return v.slots.size ? { ...v, slots: { ...v.slots, size: { ...v.slots.size, agg } } } : v;
  const values = v.slots.values.map((m, i) => (i === index && m.column !== "*" ? { ...m, agg } : m));
  return { ...v, slots: { ...v.slots, values } };
}

/** Switch chart type, keeping every field that still fits (dimensions first, then measures). */
export function changeType(v: Visualization, type: VizType, dtypes: Map<string, Dtype>): Visualization {
  if (type === v.type) return v;
  let out: Visualization = { ...v, type, slots: emptySlots() };
  const s = v.slots;
  const ref = (name: string): FieldRef => ({ name, dtype: dtypes.get(name) ?? "text" });
  const dims = [s.category, ...s.rows, ...s.columns, s.color].filter((x): x is string => !!x);
  for (const d of dims) out = addField(out, ref(d));
  const ms = [...s.values, ...(s.size ? [s.size] : [])];
  for (const m of ms) {
    const before = out;
    out = addField(out, ref(m.column));
    if (out !== before) {
      // addField picks the default aggregate: restore the chosen one
      const idx = out.slots.values.findIndex((x) => x.column === m.column);
      if (idx >= 0) out = setAgg(out, "values", idx, m.agg);
    }
  }
  return out;
}

/** Labels of the required slots that are still empty. */
export function missingSlots(v: Visualization): string[] {
  return SLOT_DEFS[v.type].filter((d) => d.required && slotCount(v.slots, d.slot) < (v.type === "scatter" && d.slot === "values" ? 2 : 1)).map((d) => d.label)
    .concat(v.type === "table" && v.slots.rows.length + v.slots.values.length === 0 ? ["Columns or Measures"] : []);
}
export function isComplete(v: Visualization): boolean { return missingSlots(v).length === 0; }

/** The dimensions a query groups by, in the order the option builder reads them. */
export function dimensionsOf(v: Visualization): string[] {
  const s = v.slots;
  switch (v.type) {
    case "bar": case "line": case "area": case "scatter":
      return [s.category, s.color].filter((x): x is string => !!x);
    case "pie": case "donut": case "funnel": case "treemap": return s.category ? [s.category] : [];
    case "heatmap": return [s.rows[0], s.columns[0]].filter((x): x is string => !!x);
    case "kpi": return [];
    case "table": return s.rows;
    case "pivot": return [...s.rows, ...s.columns];
  }
}

export function measuresOf(v: Visualization): Measure[] {
  const s = v.slots;
  switch (v.type) {
    case "scatter": return [...s.values.slice(0, 2), ...(s.size ? [s.size] : [])];
    case "bar": case "line": case "area": return s.color ? s.values.slice(0, 1) : s.values;
    case "pie": case "donut": case "funnel": case "treemap": case "heatmap": case "kpi": return s.values.slice(0, 1);
    default: return s.values;
  }
}

export function buildQuery(v: Visualization, filters: Filter[]): QueryRequest | null {
  if (!isComplete(v)) return null;
  const dimensions = [...new Set(dimensionsOf(v))];
  const measures = measuresOf(v);
  const names = [...dimensions, ...measures.map(measureName)];
  let sort: QueryRequest["sort"] = [];
  const isTimeline = (v.type === "line" || v.type === "area") && v.slots.category;
  if (isTimeline) sort = [{ by: v.slots.category as string, descending: false }];
  else if (v.options.sort_by && names.includes(v.options.sort_by))
    sort = [{ by: v.options.sort_by, descending: v.options.descending }];
  const limit = v.type === "kpi" ? 1 : Math.min(5000, Math.max(1, v.options.limit));
  return { source: v.source, dimensions, measures, filters, sort, limit };
}

// --- cross-filtering --------------------------------------------------------------------------
export interface CrossFilter { vizId: string; column: string; value: string | number | boolean | null; label: string }
export type CrossAction =
  | { type: "toggle"; filter: CrossFilter }
  | { type: "remove"; vizId: string; column: string }
  | { type: "dropViz"; vizId: string }
  | { type: "clear" };

const same = (a: CrossFilter, b: CrossFilter) => a.vizId === b.vizId && a.column === b.column && a.value === b.value;

/** One selection per visualization; clicking the selected mark again clears it. */
export function reduceCross(state: CrossFilter[], a: CrossAction): CrossFilter[] {
  switch (a.type) {
    case "toggle":
      if (state.some((f) => same(f, a.filter))) return state.filter((f) => !same(f, a.filter));
      return [...state.filter((f) => f.vizId !== a.filter.vizId), a.filter];
    case "remove": return state.filter((f) => !(f.vizId === a.vizId && f.column === a.column));
    case "dropViz": return state.filter((f) => f.vizId !== a.vizId);
    case "clear": return [];
  }
}

/** Filters one visualization receives from the others; columns its source lacks are skipped. */
export function crossFiltersFor(state: CrossFilter[], vizId: string, columns: ReadonlySet<string> | null): Filter[] {
  return state
    .filter((f) => f.vizId !== vizId && (columns === null || columns.has(f.column)))
    .map((f) => (f.value === null ? { column: f.column, op: "is_null" as const } : { column: f.column, op: "eq" as const, value: f.value }));
}

export function selectedValue(state: CrossFilter[], vizId: string): CrossFilter | undefined {
  return state.find((f) => f.vizId === vizId);
}

// --- layout -------------------------------------------------------------------------------------
export const SIZES = [3, 4, 6, 8, 12];

/** Layout items in reading order; visualizations without an item are appended, orphans dropped. */
export function orderedLayout(c: Pick<Canvas, "layout" | "visualizations">): LayoutItem[] {
  const ids = new Set(c.visualizations.map((v) => v.id));
  const items = c.layout.filter((l) => ids.has(l.viz_id)).sort((a, b) => a.y - b.y || a.x - b.x);
  const placed = new Set(items.map((i) => i.viz_id));
  for (const v of c.visualizations) if (!placed.has(v.id)) items.push({ viz_id: v.id, x: 0, y: 0, w: v.type === "kpi" ? 4 : 6, h: v.type === "kpi" ? 2 : 4 });
  return items;
}

/** Flow the items left to right, wrapping at 12 columns; y is the row start. */
export function packLayout(items: Pick<LayoutItem, "viz_id" | "w" | "h">[]): LayoutItem[] {
  const out: LayoutItem[] = [];
  let x = 0, y = 0, rowH = 0;
  for (const it of items) {
    const w = Math.min(GRID_COLS, Math.max(1, it.w));
    if (x + w > GRID_COLS) { x = 0; y += rowH; rowH = 0; }
    out.push({ viz_id: it.viz_id, x, y, w, h: it.h });
    x += w; rowH = Math.max(rowH, it.h);
  }
  return out;
}

export function moveItem(items: LayoutItem[], from: string, to: string): LayoutItem[] {
  const a = items.findIndex((i) => i.viz_id === from), b = items.findIndex((i) => i.viz_id === to);
  if (a < 0 || b < 0 || a === b) return items;
  const next = [...items];
  const [it] = next.splice(a, 1);
  next.splice(b, 0, it as LayoutItem);
  return packLayout(next);
}

export function resizeItem(items: LayoutItem[], id: string, w: number, h: number): LayoutItem[] {
  return packLayout(items.map((i) => (i.viz_id === id ? { ...i, w, h: Math.min(40, Math.max(1, h)) } : i)));
}

export function nextVizId(c: Pick<Canvas, "visualizations">): string {
  const used = new Set(c.visualizations.map((v) => v.id));
  for (let i = 1; ; i++) if (!used.has(`v${i}`)) return `v${i}`;
}

export function columnsOf(cols: ColumnInfo[]): Map<string, Dtype> { return new Map(cols.map((c) => [c.name, c.dtype])); }

export function sourceKey(s: Source): string { return s.kind === "crm" ? `crm:${s.table}` : `flow:${s.flow_id}:${s.node_id}`; }

const AGG_WORDS: Record<string, string> = {
  sum: "Sum of", mean: "Average of", median: "Median of", min: "Minimum of", max: "Maximum of",
  count: "Count of", count_distinct: "Distinct count of",
};
/** Display-only title from the slots, used while the user has not typed one (never stored). */
export function autoTitle(v: Visualization): string {
  const ms = measuresOf(v).map((m) => (m.column === "*" ? "Number of rows" : `${AGG_WORDS[m.agg] ?? m.agg} ${m.column}`));
  const ds = dimensionsOf(v);
  const head = ms.length ? ms.join(", ") : ds.length ? ds.join(", ") : "";
  if (!head) return VIZ_LABEL[v.type];
  return ms.length && ds.length ? `${head} by ${ds.join(", ")}` : head;
}
export function displayTitle(v: Visualization): string { return v.title.trim() || autoTitle(v); }
