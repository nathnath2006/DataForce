import { describe, expect, it } from "vitest";
import { BLOCKS, PORTS, defaultConfig } from "./graph";
import { nodeState } from "./nodeState";
import type { NodeResult } from "./types";

describe("phase 2 blocks", () => {
  it("every palette block has ports and a default config of its own type", () => {
    for (const b of BLOCKS) {
      expect(PORTS[b.type]).toBeDefined();
      expect(defaultConfig(b.type).type).toBe(b.type);
    }
    for (const t of ["score", "velocity", "engagement", "touchpoint"] as const) {
      expect(BLOCKS.some((b) => b.type === t)).toBe(true);
    }
  });
  it("uses the documented defaults", () => {
    expect(defaultConfig("velocity")).toMatchObject({ fast_track_pct: 0.25, stagnant_pct: 0.75, min_stage_n: 30 });
    expect(defaultConfig("engagement")).toMatchObject({ window_days: 90, quiet_days: 30, penalty: 0.5, weights: { meeting: 3, call: 2, email: 1, other: 1 } });
  });
  it("a score block is green only when its model is verified", () => {
    const r = (status: "verified" | "not_verified"): NodeResult => ({
      node_id: "s", status: "ok", error: null, n_rows: 1, columns: [], preview: [], warnings: [], elapsed_ms: 1,
      view: { kind: "score", model_name: "m", model_kind: "svm", status, n_rows: 1, n_scored: 1, n_imputed: 0, notes: [] },
    });
    expect(nodeState(r("verified"), false)).toBe("st-ok");
    expect(nodeState(r("not_verified"), false)).toBe("st-unverified");
  });
});
