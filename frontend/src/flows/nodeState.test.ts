import { describe, expect, it } from "vitest";
import { nodeState } from "./nodeState";
import type { NodeResult, StatsRow, View } from "./types";

const row = (status: StatsRow["status"]): StatsRow => ({
  group: "g", n: 40, value: 0.5, ci_low: 0.4, ci_high: 0.6, rest_value: 0.3, diff: 0.2, diff_ci_low: 0.1,
  diff_ci_high: 0.3, p_value: 0.01, q_value: 0.02, status, reasons: [],
});
const res = (view: View | null, over: Partial<NodeResult> = {}): NodeResult => ({
  node_id: "n", status: "ok", error: null, n_rows: 10, columns: [], preview: [], view, warnings: [], elapsed_ms: 1, ...over,
});
const stats = (...s: StatsRow["status"][]): View => ({
  kind: "stats", outcome: "won", outcome_kind: "rate", method: "wilson", overall: row("verified"), rows: s.map(row),
  excluded_missing: 0, gates: {},
});
const model = (status: "verified" | "not_verified"): View => ({
  kind: "model", model: "logistic_regression", n_train: 100, n_test: 30, dropped_missing: 0, metrics: [],
  coefficients: [], confusion: null, status, reasons: [],
});

describe("nodeState", () => {
  it("is green only for results the engine verified", () => {
    expect(nodeState(res(model("verified")), false)).toBe("st-ok");
    expect(nodeState(res(stats("not_verified", "verified")), false)).toBe("st-ok");
  });
  it("never shows a not-verified or exploratory result as verified", () => {
    expect(nodeState(res(model("not_verified")), false)).toBe("st-unverified");
    expect(nodeState(res(stats("not_verified", "not_verified")), false)).toBe("st-unverified");
    expect(nodeState(res({ kind: "cluster", k: 3, sizes: [], centroids: [], metrics: [], dropped_missing: 0, status: "exploratory" }), false)).toBe("st-unverified");
    expect(nodeState(res(null, { status: "skipped" }), false)).toBe("st-unverified");
  });
  it("keeps the engine's verdict when a block also carries warnings", () => {
    expect(nodeState(res(stats("verified"), { warnings: ["12 rows excluded"] }), false)).toBe("st-ok");
    expect(nodeState(res(stats("not_verified"), { warnings: ["12 rows excluded"] }), false)).toBe("st-unverified");
    expect(nodeState(res(null, { warnings: ["rows truncated"] }), false)).toBe("");
  });
  it("errors win over selection, selection over results, idle otherwise", () => {
    expect(nodeState(res(model("verified"), { status: "error" }), true)).toBe("st-bad");
    expect(nodeState(res(model("verified")), true)).toBe("st-sel");
    expect(nodeState(undefined, false)).toBe("");
    expect(nodeState(res(null), false)).toBe("");
  });
});
