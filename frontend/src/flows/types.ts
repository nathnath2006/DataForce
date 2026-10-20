// Mirrors backend/app/flows/schemas.py (the contract). Keep in sync by hand.
export type Scalar = string | number | boolean | null;
export type CrmTable =
  | "deals" | "accounts" | "contacts" | "companies" | "meetings" | "meeting_themes" | "deal_theme_flags"
  | "activities" | "stage_events" | "tasks";

export type DatasetSource =
  | { source: "crm"; table: CrmTable }
  | { source: "file"; file_id: string }
  | { source: "postgres"; connection_id: string; table?: string | null; query?: string | null };

export type FilterOp =
  | "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "contains" | "not_contains" | "is_null" | "not_null" | "in";
export interface Condition { column: string; op: FilterOp; value: Scalar | Scalar[] }
export interface SortKey { column: string; descending: boolean }
export interface Operand { column?: string | null; value?: number | null }
export type ComputedOp = "add" | "sub" | "mul" | "div" | "days_between" | "bucket";
export interface Computed {
  name: string; op: ComputedOp; left: Operand; right?: Operand | null;
  edges?: number[] | null; labels?: string[] | null;
}
export type AggFn = "count" | "count_distinct" | "sum" | "mean" | "median" | "min" | "max";
export interface Aggregation { column: string | null; fn: AggFn; as: string }
export interface JoinKey { left: string; right: string }

export type BlockConfig =
  | { type: "dataset"; dataset: DatasetSource }
  | { type: "filter"; mode: "all" | "any"; conditions: Condition[] }
  | { type: "sort"; keys: SortKey[]; limit?: number | null }
  | { type: "columns"; keep: string[] | null; rename: Record<string, string>; computed: Computed[] }
  | { type: "group"; by: string[]; aggregations: Aggregation[] }
  | { type: "join"; how: "inner" | "left"; on: JoinKey[]; suffix: string }
  | {
      type: "pivot"; rows: string[]; columns: string | null; values: string | null;
      fn: AggFn; totals: boolean; max_columns: number;
    }
  | {
      type: "stats"; group_by: string; outcome: string; outcome_kind: "rate" | "median";
      success_value: Scalar;
    }
  | {
      type: "chart"; kind: "bar" | "line" | "scatter"; x: string; y: string | null;
      series: string | null; agg: "count" | "sum" | "mean" | "median" | "none"; max_points: number;
    }
  | {
      type: "split"; test_fraction: number; seed: number; stratify: string | null;
      mode?: "random" | "chronological"; date_column?: string | null;
    }
  | {
      type: "model"; kind: ModelKind; target: string;
      features: string[]; positive_value: Scalar;
      kernel?: "rbf" | "linear"; C?: number; gamma?: number | null;
    }
  | { type: "cluster"; kind: "kmeans"; k: number; features: string[]; seed: number }
  | {
      type: "dedup"; column: string; method: "jaro_winkler" | "levenshtein"; threshold: number;
      block_prefix: number;
    }
  | {
      type: "aging"; column: string; alias: string; stagnant_after_days: number;
      where: Condition[]; where_mode: "all" | "any";
    }
  | {
      type: "forecast"; amount: string; stage: string; probabilities: Record<string, number>;
      group_by: string | null;
    }
  | {
      type: "window"; fn: WindowFn; column: string | null; partition_by: string[]; order_by: string;
      descending: boolean; k: number; alias: string; period: "month" | "quarter" | "year" | null;
    }
  | { type: "domain"; column: string; alias: string }
  | {
      type: "standardize"; columns: string[]; operations: StdOp[]; output: "overwrite" | "new_column";
      mapping: Record<string, string>; mapping_ignore_case: boolean; country: PhoneCountry;
    }
  | {
      type: "regex"; column: string; mode: RegexMode; pattern: string; replacement: string;
      ignore_case: boolean; alias: string | null; split_into: number;
    }
  | { type: "score"; model_id: string }
  | {
      type: "velocity"; deal_column: string; to_stage_column: string; date_column: string;
      fast_track_pct: number; stagnant_pct: number; min_stage_n: number; terminal_stages: string[]; include_open_stage: boolean;
    }
  | {
      type: "engagement"; by: string; kind_column: string; date_column: string; window_days: number;
      quiet_days: number; penalty: number; weights: Record<string, number>;
    }
  | { type: "touchpoint"; by: string; kind_column: string; direction_column: string; meeting_weight: number; min_outreach: number };

export type ModelKind = "linear_regression" | "logistic_regression" | "svm" | "svr";
export type WindowFn =
  | "lag" | "lead" | "rolling_mean" | "rolling_sum" | "rolling_count" | "rank" | "row_number" | "pct_change";

export type BlockType = BlockConfig["type"];

export interface GraphNode {
  id: string; label?: string | null; position: { x: number; y: number }; config: BlockConfig;
}
export interface GraphEdge {
  id: string; source: string; source_port: string; target: string; target_port: string;
}
export interface FlowGraph { version: 1; nodes: GraphNode[]; edges: GraphEdge[] }

export type Dtype = "number" | "integer" | "text" | "boolean" | "date" | "datetime" | "other";
export interface ColumnInfo { name: string; dtype: Dtype }

export interface PivotView {
  kind: "pivot"; row_headers: string[]; column_values: string[];
  rows: { keys: unknown[]; cells: unknown[] }[]; truncated_columns: number;
}
export interface ChartView {
  kind: "chart"; chart: "bar" | "line" | "scatter"; x_label: string; y_label: string;
  series: { name: string; points: [unknown, number | null][] }[]; truncated: boolean;
}
export interface StatsRow {
  group: string; n: number; value: number | null; ci_low: number | null; ci_high: number | null;
  rest_value: number | null; diff: number | null; diff_ci_low: number | null; diff_ci_high: number | null;
  p_value: number | null; q_value: number | null; status: "verified" | "not_verified"; reasons: string[];
}
export interface StatsView {
  kind: "stats"; outcome: string; outcome_kind: "rate" | "median"; method: string;
  overall: StatsRow; rows: StatsRow[]; excluded_missing: number; gates: Record<string, unknown>;
}
export interface MetricOut {
  name: string; value: number | null; ci_low?: number | null; ci_high?: number | null; baseline?: number | null;
}
export interface ModelView {
  kind: "model"; model: ModelKind; n_train: number; n_test: number;
  dropped_missing: number; metrics: MetricOut[]; coefficients: { feature: string; coef: number }[];
  confusion: number[][] | null; status: "verified" | "not_verified"; reasons: string[]; caveats?: string[];
}
export interface ClusterView {
  kind: "cluster"; k: number; sizes: number[]; centroids: Record<string, unknown>[];
  metrics: MetricOut[]; dropped_missing: number; status: "exploratory";
}
export type ModelStatus = "verified" | "not_verified" | "exploratory";
export interface ScoreView {
  kind: "score"; model_name: string; model_kind: string; status: ModelStatus; n_rows: number;
  n_scored: number; n_imputed: number; notes: string[];
}
export interface VelocityView {
  kind: "velocity"; benchmark_note: string; benchmarks: { stage: string; median_days: number | null; n: number; p75_days: number | null; sufficient: boolean }[];
  fast_track_pct: number; stagnant_pct: number; min_stage_n: number; counts: Record<string, number>; n_stalled: number;
}
export interface EngagementView {
  kind: "engagement"; today: string; window_days: number; quiet_days: number; penalty: number;
  weights: Record<string, number>; n_accounts: number; n_penalised: number; formula: string;
  label?: string; caveats?: string[];
}
export type StdOp =
  | "trim" | "collapse_spaces" | "lower" | "upper" | "title" | "remove_accents" | "normalize_unicode"
  | "strip_punctuation" | "empty_to_null" | "map_values" | "phone_e164" | "email";
export type PhoneCountry = "FR" | "BE" | "CH" | "DE" | "GB" | "ES" | "IT" | "PT" | "NL" | "US" | "CA";
export type RegexMode = "extract" | "replace" | "match" | "split";
export interface StandardizeView {
  kind: "standardize"; n_rows: number;
  columns: { column: string; output: string; n_changed: number; n_null: number; n_flagged: number }[];
}
export interface RegexView {
  kind: "regex"; mode: RegexMode; n_cells: number; n_matched: number; match_rate: number | null;
  n_truncated: number; new_columns: string[];
}
export interface ForecastView { kind: "forecast"; label: string; probabilities: Record<string, number>; n_unmapped: number }
export interface TouchpointView { kind: "touchpoint"; formula: string; n_groups: number; n_no_outreach: number; min_outreach: number; n_below_min: number }
export type View =
  | PivotView | ChartView | StatsView | ModelView | ClusterView
  | ScoreView | VelocityView | EngagementView | TouchpointView | ForecastView | StandardizeView | RegexView;

export interface NodeResult {
  node_id: string; status: "ok" | "error" | "skipped"; error: string | null; n_rows: number | null;
  columns: ColumnInfo[]; profile?: ColumnProfile[] | null; preview: Record<string, unknown>[]; view: View | null;
  model_params?: Record<string, unknown> | null;
  warnings: string[]; elapsed_ms: number;
}
export interface RunResponse { run_id: string | null; started_at: string; results: Record<string, NodeResult> }

export interface FlowSummary { id: string; name: string; description: string | null; n_nodes: number; updated_at: string }
export interface FlowOut {
  id: string; name: string; description: string | null; graph: FlowGraph; created_at: string; updated_at: string;
}
export interface Catalog {
  blocks: Record<string, { inputs: string[]; outputs: string[] }>;
  crm_tables: Record<string, ColumnInfo[]>;
}
export interface FileOut {
  id: string; name: string; size_bytes: number; media_type: string; sheet: string | null;
  n_rows: number; columns: ColumnInfo[]; created_at: string;
}
export interface ConnectionIn {
  name: string; host: string; port: number; database: string; username: string;
  password?: string; sslmode: string;
}
export interface ConnectionOut {
  id: string; name: string; host: string; port: number; database: string; username: string;
  sslmode: string; last_test_at?: string | null; last_test_ok?: boolean | null; last_error?: string | null; has_password?: boolean;
  [k: string]: unknown;
}
export interface PgTable { schema: string; name: string }

export interface ColumnProfile {
  name: string; dtype: ColumnInfo["dtype"]; n: number; non_null: number; n_unique: number; n_unique_capped: boolean;
  hist: { min: number; max: number; counts: number[] } | null;
  top: { value: string; count: number }[] | null;
}
