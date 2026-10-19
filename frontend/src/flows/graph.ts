import type { Edge as XEdge, Node as XNode } from "@xyflow/react";
import type {
  BlockConfig, BlockType, Catalog, ColumnInfo, FileOut, FlowGraph, GraphEdge, GraphNode, NodeResult,
} from "./types";

/** Input and output ports of each block, as in backend PORTS. */
export const PORTS: Record<BlockType, { inputs: string[]; outputs: string[] }> = {
  dataset: { inputs: [], outputs: ["out"] },
  filter: { inputs: ["in"], outputs: ["out"] },
  sort: { inputs: ["in"], outputs: ["out"] },
  columns: { inputs: ["in"], outputs: ["out"] },
  group: { inputs: ["in"], outputs: ["out"] },
  join: { inputs: ["left", "right"], outputs: ["out"] },
  pivot: { inputs: ["in"], outputs: ["out"] },
  stats: { inputs: ["in"], outputs: ["out"] },
  chart: { inputs: ["in"], outputs: [] },
  split: { inputs: ["in"], outputs: ["train", "test"] },
  model: { inputs: ["train", "test"], outputs: ["out"] },
  cluster: { inputs: ["in"], outputs: ["out"] },
  dedup: { inputs: ["in"], outputs: ["out"] },
  aging: { inputs: ["in"], outputs: ["out"] },
  forecast: { inputs: ["in"], outputs: ["out"] },
  window: { inputs: ["in"], outputs: ["out"] },
  domain: { inputs: ["in"], outputs: ["out"] },
  score: { inputs: ["in"], outputs: ["out"] },
  velocity: { inputs: ["in"], outputs: ["out"] },
  engagement: { inputs: ["in"], outputs: ["out"] },
  touchpoint: { inputs: ["in"], outputs: ["out"] },
};

export type PaletteGroup = "Data" | "Transform" | "Cleaning" | "Temporal" | "Aggregation" | "Analyze" | "Model" | "Visualize";
export const BLOCKS: { type: BlockType; title: string; group: PaletteGroup }[] = [
  { type: "dataset", title: "Dataset", group: "Data" },
  { type: "filter", title: "Filter", group: "Transform" },
  { type: "sort", title: "Sort", group: "Transform" },
  { type: "columns", title: "Columns", group: "Transform" },
  { type: "group", title: "Group / aggregate", group: "Transform" },
  { type: "join", title: "Join", group: "Transform" },
  { type: "dedup", title: "Fuzzy dedup", group: "Cleaning" },
  { type: "domain", title: "Domain parser", group: "Cleaning" },
  { type: "aging", title: "Aging and stagnation", group: "Temporal" },
  { type: "window", title: "Window (lag, rolling, rank)", group: "Temporal" },
  { type: "forecast", title: "Weighted forecast", group: "Aggregation" },
  { type: "pivot", title: "Pivot", group: "Analyze" },
  { type: "stats", title: "Stats test", group: "Analyze" },
  { type: "split", title: "Train / test split", group: "Model" },
  { type: "model", title: "Regression model", group: "Model" },
  { type: "cluster", title: "K-means clusters", group: "Model" },
  { type: "velocity", title: "Deal velocity index", group: "Temporal" },
  { type: "engagement", title: "Engagement score", group: "Analyze" },
  { type: "touchpoint", title: "Rep touchpoint ratio", group: "Analyze" },
  { type: "score", title: "Score with a saved model", group: "Model" },
  { type: "chart", title: "Chart", group: "Visualize" },
];
export const PALETTE_GROUPS: PaletteGroup[] = ["Data", "Transform", "Cleaning", "Temporal", "Aggregation", "Analyze", "Model", "Visualize"];
export const blockTitle = (t: string): string => BLOCKS.find((b) => b.type === t)?.title ?? t;

/** Stage win probabilities in percent: the user's assumptions, not a statistical estimate. */
export const DEFAULT_PROBABILITIES: Record<string, number> = {
  prospecting: 10, qualification: 20, proposal: 40, negotiation: 60, closed_won: 100, closed_lost: 0,
};

export const DEFAULT_ENGAGEMENT_WEIGHTS: Record<string, number> = { meeting: 3, call: 2, email: 1, other: 1 };

export function defaultConfig(type: BlockType): BlockConfig {
  switch (type) {
    case "dataset": return { type, dataset: { source: "crm", table: "deals" } };
    case "filter": return { type, mode: "all", conditions: [] };
    case "sort": return { type, keys: [{ column: "", descending: false }], limit: null };
    case "columns": return { type, keep: null, rename: {}, computed: [] };
    case "group": return { type, by: [], aggregations: [{ column: null, fn: "count", as: "n" }] };
    case "join": return { type, how: "left", on: [{ left: "", right: "" }], suffix: "_right" };
    case "pivot": return { type, rows: [], columns: null, values: null, fn: "count", totals: true, max_columns: 50 };
    case "stats": return { type, group_by: "", outcome: "", outcome_kind: "rate", success_value: true };
    case "chart": return { type, kind: "bar", x: "", y: null, series: null, agg: "count", max_points: 2000 };
    case "split": return { type, test_fraction: 0.25, seed: 42, stratify: null, mode: "random", date_column: null };
    case "model": return { type, kind: "logistic_regression", target: "", features: [], positive_value: true };
    case "cluster": return { type, kind: "kmeans", k: 3, features: [], seed: 42 };
    case "dedup": return { type, column: "", method: "jaro_winkler", threshold: 0.92, block_prefix: 1 };
    case "aging": return { type, column: "", alias: "days_since", stagnant_after_days: 30, where: [], where_mode: "all" };
    case "forecast": return { type, amount: "", stage: "", probabilities: { ...DEFAULT_PROBABILITIES }, group_by: null };
    case "window":
      return { type, fn: "lag", column: null, partition_by: [], order_by: "", descending: false, k: 1, alias: "window_value", period: null };
    case "domain": return { type, column: "", alias: "domain" };
    case "score": return { type, model_id: "" };
    case "velocity":
      return {
        type, deal_column: "deal_id", to_stage_column: "to_stage", date_column: "changed_at", fast_track_at: 1.25,
        stagnant_below: 0.75, terminal_stages: ["closed_won", "closed_lost"], include_open_stage: true,
      };
    case "engagement":
      return {
        type, by: "account_id", kind_column: "kind", date_column: "occurred_at", window_days: 90, quiet_days: 30,
        penalty: 0.5, weights: { ...DEFAULT_ENGAGEMENT_WEIGHTS },
      };
    case "touchpoint": return { type, by: "author", kind_column: "kind", direction_column: "direction", meeting_weight: 3 };
  }
}

export function newId(prefix: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  for (let i = 1; ; i++) {
    const id = `${prefix}${i}`;
    if (!used.has(id)) return id;
  }
}

export const emptyGraph = (): FlowGraph => ({ version: 1, nodes: [], edges: [] });

// ---- xyflow conversion ----
export interface BlockData extends Record<string, unknown> { config: BlockConfig; label: string | null }
export type BlockNode = XNode<BlockData, "block">;

export function toFlowNodes(g: FlowGraph): BlockNode[] {
  return g.nodes.map((n) => ({
    id: n.id, type: "block" as const, position: { x: n.position.x, y: n.position.y },
    data: { config: n.config, label: n.label ?? null },
  }));
}
export function toFlowEdges(g: FlowGraph): XEdge[] {
  return g.edges.map((e) => ({
    id: e.id, source: e.source, sourceHandle: e.source_port, target: e.target, targetHandle: e.target_port,
  }));
}
export function fromFlow(nodes: BlockNode[], edges: XEdge[]): FlowGraph {
  const gn: GraphNode[] = nodes.map((n) => {
    const label = n.data.label?.trim();
    return {
      id: n.id, ...(label ? { label } : {}),
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) }, config: n.data.config,
    };
  });
  const ge: GraphEdge[] = edges.map((e) => ({
    id: e.id, source: e.source, source_port: e.sourceHandle ?? "out",
    target: e.target, target_port: e.targetHandle ?? "in",
  }));
  return { version: 1, nodes: gn, edges: ge };
}

/** The graph as the editor would save it, so a freshly opened flow compares equal (labels saved as
 *  null, positions saved as 0.0). */
export function normalizeGraph(g: FlowGraph): FlowGraph {
  return fromFlow(toFlowNodes(g), toFlowEdges(g));
}

// ---- connection validation ----
export interface Conn { source: string; sourceHandle: string | null; target: string; targetHandle: string | null }

/** True when adding source -> target would close a cycle. */
export function wouldCycle(edges: { source: string; target: string }[], source: string, target: string): boolean {
  if (source === target) return true;
  const next = new Map<string, string[]>();
  for (const e of edges) next.set(e.source, [...(next.get(e.source) ?? []), e.target]);
  const seen = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const cur = stack.pop() as string;
    if (cur === source) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    stack.push(...(next.get(cur) ?? []));
  }
  return false;
}

/** Why a connection is refused, or null when allowed. */
export function connectionError(
  nodes: { id: string; type: BlockType }[],
  edges: { source: string; target: string; targetHandle?: string | null }[],
  c: Conn,
): string | null {
  const s = nodes.find((n) => n.id === c.source);
  const t = nodes.find((n) => n.id === c.target);
  if (!s || !t) return "Unknown block";
  if (!c.sourceHandle || !PORTS[s.type].outputs.includes(c.sourceHandle)) return "Not an output port";
  if (!c.targetHandle || !PORTS[t.type].inputs.includes(c.targetHandle)) return "Not an input port";
  if (edges.some((e) => e.target === c.target && (e.targetHandle ?? "in") === c.targetHandle)) {
    return "This input already has a connection";
  }
  if (wouldCycle(edges, c.source, c.target)) return "This would create a cycle";
  return null;
}

/** Structural problems of a graph (mirrors the backend validator). Empty means valid. */
export function validateGraph(g: FlowGraph): string[] {
  const errs: string[] = [];
  const types = new Map(g.nodes.map((n) => [n.id, n.config.type] as const));
  if (types.size !== g.nodes.length) errs.push("duplicate block ids");
  const taken = new Set<string>();
  const acc: { source: string; target: string }[] = [];
  for (const e of g.edges) {
    const st = types.get(e.source), tt = types.get(e.target);
    if (!st || !tt) { errs.push(`edge ${e.id} references a missing block`); continue; }
    if (!PORTS[st].outputs.includes(e.source_port)) errs.push(`edge ${e.id}: bad output port`);
    if (!PORTS[tt].inputs.includes(e.target_port)) errs.push(`edge ${e.id}: bad input port`);
    const k = `${e.target}/${e.target_port}`;
    if (taken.has(k)) errs.push(`input ${e.target_port} of ${e.target} has two edges`);
    taken.add(k);
    if (wouldCycle(acc, e.source, e.target)) errs.push("the flow has a cycle");
    acc.push(e);
  }
  return errs;
}

/** Ids of a node and everything upstream of it. */
// ---- column inference for the pickers ----
export interface ColumnCtx {
  results: Record<string, NodeResult>;
  catalog: Catalog | null;
  files: FileOut[];
}

export function datasetColumns(c: BlockConfig, ctx: ColumnCtx): ColumnInfo[] {
  if (c.type !== "dataset") return [];
  const d = c.dataset;
  if (d.source === "crm") return ctx.catalog?.crm_tables[d.table] ?? [];
  if (d.source === "file") return ctx.files.find((f) => f.id === d.file_id)?.columns ?? [];
  return [];
}

/** Columns arriving at `port` of `nodeId`: from the latest run when available, else inferred. */
export function inputColumns(g: FlowGraph, nodeId: string, port: string, ctx: ColumnCtx, depth = 0): ColumnInfo[] {
  const edge = g.edges.find((e) => e.target === nodeId && e.target_port === port);
  if (!edge || depth > 50) return [];
  return outputColumns(g, edge.source, ctx, depth + 1);
}

export function outputColumns(g: FlowGraph, id: string, ctx: ColumnCtx, depth = 0): ColumnInfo[] {
  const run = ctx.results[id];
  if (run && run.status === "ok" && run.columns.length) return run.columns;
  const node = g.nodes.find((n) => n.id === id);
  if (!node) return [];
  const c = node.config;
  const up = () => inputColumns(g, id, c.type === "model" ? "test" : "in", ctx, depth);
  switch (c.type) {
    case "dataset": return datasetColumns(c, ctx);
    case "filter": case "sort": case "split": return up();
    case "cluster": return [...up(), { name: "cluster", dtype: "integer" }];
    case "dedup": return [...up(), { name: "dedup_group", dtype: "integer" }, { name: "is_master", dtype: "boolean" }];
    case "aging": return [...up(), { name: c.alias || "days_since", dtype: "number" }, { name: "stagnant", dtype: "boolean" }];
    case "domain": return [...up(), { name: c.alias || "domain", dtype: "text" }, { name: "is_free_webmail", dtype: "boolean" }];
    case "score": return [...up(), { name: "score", dtype: "number" }];
    case "velocity": return [{ name: c.deal_column || "deal_id", dtype: "text" }, { name: "velocity_index", dtype: "number" }, { name: "velocity_flag", dtype: "text" }];
    case "engagement": return [{ name: c.by || "account_id", dtype: "text" }, { name: "engagement_score", dtype: "number" }];
    case "touchpoint": return [{ name: c.by || "author", dtype: "text" }, { name: "touchpoint_ratio", dtype: "number" }];
    case "forecast": {
      const base = up();
      if (!c.group_by) return [...base, { name: "probability", dtype: "number" }, { name: "weighted_amount", dtype: "number" }];
      return [
        base.find((x) => x.name === c.group_by) ?? { name: c.group_by, dtype: "other" as const },
        { name: "n", dtype: "integer" }, { name: "amount", dtype: "number" }, { name: "weighted_amount", dtype: "number" },
      ];
    }
    case "window": {
      const alias = { name: c.alias || "window_value", dtype: "number" as const };
      const base = up();
      if (!c.period) return [...base, alias];
      const pick = (n: string) => base.find((x) => x.name === n) ?? { name: n, dtype: "other" as const };
      return [...c.partition_by.map(pick), { name: "period", dtype: "text" as const }, ...(c.column ? [pick(c.column)] : []), alias];
    }
    case "group": {
      const base = up();
      const by = c.by.map((n) => base.find((x) => x.name === n) ?? { name: n, dtype: "other" as const });
      return [...by, ...c.aggregations.filter((a) => a.as).map((a) => ({ name: a.as, dtype: "number" as const }))];
    }
    case "columns": {
      let cols = up();
      if (c.keep) cols = c.keep.map((n) => cols.find((x) => x.name === n) ?? { name: n, dtype: "other" as const });
      cols = cols.map((x) => ({ ...x, name: c.rename[x.name] || x.name }));
      return [...cols, ...c.computed.filter((x) => x.name).map((x) => ({
        name: x.name, dtype: x.op === "bucket" ? ("text" as const) : ("number" as const),
      }))];
    }
    case "join": {
      const l = inputColumns(g, id, "left", ctx, depth), r = inputColumns(g, id, "right", ctx, depth);
      const have = new Set(l.map((x) => x.name));
      return [...l, ...r.map((x) => (have.has(x.name) ? { ...x, name: x.name + c.suffix } : x))];
    }
    default: return [];
  }
}

// ---- templates (section 7.1) ----
const node = (id: string, x: number, y: number, config: BlockConfig, label?: string): GraphNode =>
  ({ id, ...(label ? { label } : {}), position: { x, y }, config });
const edge = (id: string, source: string, target: string, source_port = "out", target_port = "in"): GraphEdge =>
  ({ id, source, source_port, target, target_port });

/** "Themes vs win rate (theme X)": closed deals, win rate split by whether the theme was mentioned. */
export function themesVsWinRateGraph(theme: string): FlowGraph {
  return {
    version: 1,
    nodes: [
      node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deal_theme_flags" } }, "Deal themes"),
      node("n2", 280, 0, {
        type: "filter", mode: "all",
        conditions: [{ column: "theme", op: "eq", value: theme }, { column: "is_closed", op: "eq", value: true }],
      }, "Theme, closed only"),
      node("n3", 560, 0, { type: "stats", group_by: "mentioned", outcome: "is_won", outcome_kind: "rate", success_value: true }),
    ],
    edges: [edge("e1", "n1", "n2"), edge("e2", "n2", "n3")],
  };
}

export interface Template { key: string; title: string; description: string; build: () => FlowGraph }
export const TEMPLATES: Template[] = [
  {
    key: "pivot", title: "Deals pivot (segment × stage)", description: "Count of deals by segment and stage.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deals" } }, "Deals"),
        node("n2", 280, 0, { ...(defaultConfig("pivot") as Extract<BlockConfig, { type: "pivot" }>), rows: ["segment"], columns: "stage" }),
      ],
      edges: [edge("e1", "n1", "n2")],
    }),
  },
  {
    key: "stats", title: "Win rate by lead source (stats)", description: "Closed deals, win rate per lead source vs the rest.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deals" } }, "Deals"),
        node("n2", 280, 0, { type: "filter", mode: "all", conditions: [{ column: "is_closed", op: "eq", value: true }] }, "Closed only"),
        node("n3", 560, 0, { type: "stats", group_by: "lead_source", outcome: "is_won", outcome_kind: "rate", success_value: true }),
      ],
      edges: [edge("e1", "n1", "n2"), edge("e2", "n2", "n3")],
    }),
  },
  {
    key: "model", title: "Predict won deals (split + logistic)", description: "Logistic regression on closed deals.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deals" } }, "Deals"),
        node("n2", 260, 0, { type: "filter", mode: "all", conditions: [{ column: "is_closed", op: "eq", value: true }] }, "Closed only"),
        node("n3", 520, 0, { type: "split", test_fraction: 0.25, seed: 42, stratify: "is_won" }),
        node("n4", 800, 40, {
          type: "model", kind: "logistic_regression", target: "is_won",
          features: ["lead_source", "segment", "amount_eur"], positive_value: true,
        }),
      ],
      edges: [
        edge("e1", "n1", "n2"), edge("e2", "n2", "n3"),
        edge("e3", "n3", "n4", "train", "train"), edge("e4", "n3", "n4", "test", "test"),
      ],
    }),
  },
  {
    key: "cluster", title: "Cluster accounts (k-means)", description: "Three clusters on size and deal history.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "accounts" } }, "Accounts"),
        node("n2", 280, 0, { type: "cluster", kind: "kmeans", k: 3, features: ["employee_count", "n_deals", "won_amount_eur"], seed: 42 }),
      ],
      edges: [edge("e1", "n1", "n2")],
    }),
  },
  {
    key: "forecast", title: "Weighted pipeline forecast", description: "Open deals: amount × stage probability, totalled per owner. Probabilities are your assumptions.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deals" } }, "Deals"),
        node("n2", 280, 0, { type: "filter", mode: "all", conditions: [{ column: "is_closed", op: "eq", value: false }] }, "Open deals"),
        node("n3", 560, 0, { ...(defaultConfig("forecast") as Extract<BlockConfig, { type: "forecast" }>), amount: "amount_eur", stage: "stage", group_by: "owner" }),
      ],
      edges: [edge("e1", "n1", "n2"), edge("e2", "n2", "n3")],
    }),
  },
  {
    key: "stalled", title: "Stalled deals", description: "Open deals created more than 45 days ago, oldest first.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deals" } }, "Deals"),
        node("n2", 280, 0, {
          type: "aging", column: "created_on", alias: "days_since", stagnant_after_days: 45,
          where: [{ column: "is_closed", op: "eq", value: false }], where_mode: "all",
        }, "Days since created"),
        node("n3", 560, 0, { type: "filter", mode: "all", conditions: [{ column: "stagnant", op: "eq", value: true }] }, "Stalled only"),
        node("n4", 840, 0, { type: "sort", keys: [{ column: "days_since", descending: true }], limit: null }),
      ],
      edges: [edge("e1", "n1", "n2"), edge("e2", "n2", "n3"), edge("e3", "n3", "n4")],
    }),
  },
  {
    key: "dupes", title: "Duplicate accounts", description: "Fuzzy dedup on account names; nothing is merged in the CRM.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "accounts" } }, "Accounts"),
        node("n2", 280, 0, { type: "dedup", column: "account_name", method: "jaro_winkler", threshold: 0.92, block_prefix: 1 }),
        node("n3", 560, 0, { type: "sort", keys: [{ column: "dedup_group", descending: false }], limit: null }),
      ],
      edges: [edge("e1", "n1", "n2"), edge("e2", "n2", "n3")],
    }),
  },
  {
    key: "growth", title: "Growth per owner", description: "Closed-won amount per owner and quarter, with the change from the previous quarter.",
    build: () => ({
      version: 1,
      nodes: [
        node("n1", 0, 0, { type: "dataset", dataset: { source: "crm", table: "deals" } }, "Deals"),
        node("n2", 280, 0, { type: "filter", mode: "all", conditions: [{ column: "is_won", op: "eq", value: true }] }, "Won only"),
        node("n3", 560, 0, {
          type: "window", fn: "pct_change", column: "amount_eur", partition_by: ["owner"], order_by: "closed_on",
          descending: false, k: 1, alias: "qoq_growth", period: "quarter",
        }, "QoQ growth"),
      ],
      edges: [edge("e1", "n1", "n2"), edge("e2", "n2", "n3")],
    }),
  },
  {
    key: "themes", title: "Themes vs win rate", description: "Win rate of closed deals whose meetings mention a theme (set the theme in the filter).",
    build: () => themesVsWinRateGraph("theme label"),
  },
];

// ---- scalar text <-> value (filter values, success value, positive value) ----
export function parseScalar(s: string): string | number | boolean | null {
  const t = s.trim();
  if (t === "") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return s;
}
export function showScalar(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}
