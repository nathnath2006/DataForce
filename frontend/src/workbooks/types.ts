export type Dtype = "number" | "integer" | "text" | "boolean" | "date" | "datetime" | "other";
export interface ColumnInfo { name: string; dtype: Dtype }

export type Source =
  | { kind: "crm"; table: string }
  | { kind: "flow"; flow_id: string; node_id: string };

export type Agg = "count" | "sum" | "mean" | "median" | "min" | "max" | "count_distinct";
export interface Measure { column: string; agg: Agg }

export type FilterOp = "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "contains" | "in" | "is_null" | "not_null";
export type Scalar = string | number | boolean | null;
export interface Filter { column: string; op: FilterOp; value?: Scalar | Scalar[] }

export type VizType =
  | "bar" | "line" | "area" | "scatter" | "pie" | "donut" | "heatmap" | "treemap" | "funnel"
  | "kpi" | "table" | "pivot";

export interface Slots {
  category: string | null;
  values: Measure[];
  color: string | null;
  size: Measure | null;
  rows: string[];
  columns: string[];
}

export interface VizOptions {
  stacked: boolean; smooth: boolean; show_labels: boolean; horizontal: boolean;
  limit: number; sort_by: string | null; descending: boolean;
}

export interface Visualization {
  id: string; type: VizType; title: string; source: Source; slots: Slots; options: VizOptions;
}
export interface LayoutItem { viz_id: string; x: number; y: number; w: number; h: number }
export interface Canvas { name: string; filters: Filter[]; layout: LayoutItem[]; visualizations: Visualization[] }
export interface WorkbookSpec { version: 1; canvases: Canvas[] }

export interface WorkbookSummary { id: string; name: string; n_canvases: number; updated_at: string }
export interface WorkbookOut { id: string; name: string; spec: WorkbookSpec; created_at: string; updated_at: string }

export interface QueryRequest {
  source: Source; dimensions: string[]; measures: Measure[]; filters: Filter[];
  sort: { by: string; descending: boolean }[]; limit: number;
}
export interface QueryResponse {
  columns: ColumnInfo[]; rows: unknown[][]; n_source_rows: number; n_filtered_rows: number;
  n_groups: number; truncated_source: boolean; notes: string[];
}
export interface FieldsResponse {
  columns: ColumnInfo[]; n_source_rows: number; truncated_source: boolean; notes: string[];
}

export interface ExplainMeasure { column: string; kind: "rate" | "median"; success_value?: Scalar }
export interface ExplainFinding {
  attribute: string; group: string; n: number; value: number | null; rest_value: number | null;
  diff: number | null; diff_ci_low: number | null; diff_ci_high: number | null;
  p_value: number | null; q_value: number | null; direction: "higher" | "lower" | "none";
  status: "verified" | "not_verified"; reasons: string[];
}
export interface ExplainResponse {
  measure: ExplainMeasure; method: string; n_rows: number; truncated_source: boolean;
  verified: ExplainFinding[]; not_verified: ExplainFinding[]; notes: string[];
}
