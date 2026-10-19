import { describe, expect, it } from "vitest";
import {
  BLOCKS, PORTS, TEMPLATES, connectionError, defaultConfig, fromFlow, inputColumns, newId, outputColumns,
  normalizeGraph, toFlowEdges, toFlowNodes, validateGraph, wouldCycle,
} from "./graph";
import type { BlockType, FlowGraph } from "./types";

const chain: FlowGraph = TEMPLATES[2]!.build();

describe("conversion", () => {
  it("round-trips a graph through xyflow shapes", () => {
    const g = chain;
    expect(fromFlow(toFlowNodes(g), toFlowEdges(g))).toEqual(g);
  });
  it("maps ports to handles", () => {
    const e = toFlowEdges(chain).find((x) => x.id === "e3")!;
    expect(e.sourceHandle).toBe("train");
    expect(e.targetHandle).toBe("train");
  });
  it("drops blank labels and rounds positions", () => {
    const n = toFlowNodes(chain);
    n[0]!.data = { ...n[0]!.data, label: "  " };
    n[0]!.position = { x: 1.6, y: 2.2 };
    const out = fromFlow(n, []).nodes[0]!;
    expect(out.label).toBeUndefined();
    expect(out.position).toEqual({ x: 2, y: 2 });
  });
  it("a graph as the server stores it (label null) is not seen as unsaved", () => {
    const stored = { ...chain, nodes: chain.nodes.map((n) => ({ ...n, label: null })) } as unknown as FlowGraph;
    const editor = fromFlow(toFlowNodes(stored), toFlowEdges(stored));
    expect(JSON.stringify(editor)).toBe(JSON.stringify(normalizeGraph(stored)));
    expect(JSON.stringify(editor)).not.toBe(JSON.stringify(stored));
  });
});

describe("defaults and ports", () => {
  it("has a default config and ports for every palette block", () => {
    for (const b of BLOCKS) {
      expect(defaultConfig(b.type).type).toBe(b.type);
      expect(PORTS[b.type]).toBeDefined();
    }
    expect(BLOCKS.length).toBe(Object.keys(PORTS).length);
  });
  it("dataset defaults to the CRM deals table", () => {
    expect(defaultConfig("dataset")).toEqual({ type: "dataset", dataset: { source: "crm", table: "deals" } });
  });
  it("generates unused ids", () => {
    expect(newId("n", ["n1", "n2"])).toBe("n3");
  });
});

describe("connection rules", () => {
  const nodes = [
    { id: "a", type: "dataset" as BlockType }, { id: "b", type: "filter" as BlockType },
    { id: "c", type: "join" as BlockType }, { id: "d", type: "chart" as BlockType },
  ];
  it("accepts a valid connection", () => {
    expect(connectionError(nodes, [], { source: "a", sourceHandle: "out", target: "b", targetHandle: "in" })).toBeNull();
  });
  it("refuses a second edge into an input", () => {
    const edges = [{ source: "a", target: "b", targetHandle: "in" }];
    expect(connectionError(nodes, edges, { source: "a", sourceHandle: "out", target: "b", targetHandle: "in" })).toMatch(/already/);
    expect(connectionError(nodes, edges, { source: "a", sourceHandle: "out", target: "c", targetHandle: "left" })).toBeNull();
  });
  it("refuses cycles and self loops", () => {
    const edges = [{ source: "b", target: "c", targetHandle: "left" }];
    expect(connectionError(nodes, edges, { source: "c", sourceHandle: "out", target: "b", targetHandle: "in" })).toMatch(/cycle/);
    expect(wouldCycle([], "a", "a")).toBe(true);
  });
  it("refuses unknown ports", () => {
    expect(connectionError(nodes, [], { source: "d", sourceHandle: "out", target: "b", targetHandle: "in" })).toMatch(/output/);
    expect(connectionError(nodes, [], { source: "a", sourceHandle: "out", target: "a", targetHandle: "x" })).toMatch(/input/);
  });
});

describe("validateGraph and templates", () => {
  it("every template is valid", () => {
    for (const t of TEMPLATES) expect(validateGraph(t.build())).toEqual([]);
  });
  it("finds two edges into one input and cycles", () => {
    const g = TEMPLATES[0]!.build();
    g.edges.push({ id: "e9", source: "n1", source_port: "out", target: "n2", target_port: "in" });
    expect(validateGraph(g).join()).toMatch(/two edges/);
    const c = TEMPLATES[1]!.build();
    c.edges.push({ id: "e9", source: "n3", source_port: "out", target: "n2", target_port: "in" });
    expect(validateGraph(c).join()).toMatch(/cycle|two edges/);
  });
});

describe("column inference", () => {
  const catalog = { blocks: {}, crm_tables: { deals: [{ name: "stage", dtype: "text" as const }, { name: "amount_eur", dtype: "number" as const }] } };
  it("flows catalog columns through filter and split", () => {
    const cols = inputColumns(chain, "n4", "test", { results: {}, catalog, files: [] });
    expect(cols.map((c) => c.name)).toEqual(["stage", "amount_eur"]);
  });
  it("prefers run results", () => {
    const results = { n3: { node_id: "n3", status: "ok" as const, error: null, n_rows: 1, columns: [{ name: "z", dtype: "text" as const }], preview: [], view: null, warnings: [], elapsed_ms: 0 } };
    expect(inputColumns(chain, "n4", "test", { results, catalog, files: [] }).map((c) => c.name)).toEqual(["z"]);
  });
});

import { parseScalar, showScalar } from "./graph";
describe("scalars", () => {
  it("parses typed values", () => {
    expect(parseScalar("true")).toBe(true);
    expect(parseScalar("12.5")).toBe(12.5);
    expect(parseScalar("abc")).toBe("abc");
    expect(parseScalar(" ")).toBeNull();
    expect(showScalar(false)).toBe("false");
    expect(showScalar(null)).toBe("");
  });
});

describe("batch 1 blocks", () => {
  it("every block has a palette entry, ports and a default config of its own type", () => {
    for (const t of ["dedup", "aging", "forecast", "window", "domain"] as const) {
      expect(BLOCKS.some((b) => b.type === t)).toBe(true);
      expect(defaultConfig(t).type).toBe(t);
      expect(PORTS[t]).toEqual({ inputs: ["in"], outputs: ["out"] });
    }
    expect(BLOCKS.find((b) => b.type === "dedup")?.group).toBe("Cleaning");
    expect(BLOCKS.find((b) => b.type === "window")?.group).toBe("Temporal");
    expect(BLOCKS.find((b) => b.type === "forecast")?.group).toBe("Aggregation");
  });

  it("default forecast probabilities are the documented assumptions", () => {
    const c = defaultConfig("forecast");
    expect(c.type === "forecast" && c.probabilities).toEqual({
      prospecting: 10, qualification: 20, proposal: 40, negotiation: 60, closed_won: 100, closed_lost: 0,
    });
  });

  it("the four new templates are valid graphs", () => {
    for (const key of ["forecast", "stalled", "dupes", "growth"]) {
      const t = TEMPLATES.find((x) => x.key === key);
      expect(t, key).toBeDefined();
      expect(validateGraph(t!.build())).toEqual([]);
    }
  });

  it("infers the columns each new block adds", () => {
    const names = (key: string, id: string) =>
      outputColumns(TEMPLATES.find((x) => x.key === key)!.build(), id,
        { results: {}, catalog: { blocks: {}, crm_tables: { deals: [{ name: "owner", dtype: "text" }], accounts: [{ name: "account_name", dtype: "text" }] } }, files: [] })
        .map((c) => c.name);
    expect(names("dupes", "n2")).toEqual(["account_name", "dedup_group", "is_master"]);
    expect(names("stalled", "n2")).toEqual(["owner", "days_since", "stagnant"]);
    expect(names("growth", "n3")).toEqual(["owner", "period", "amount_eur", "qoq_growth"]);
  });
});
