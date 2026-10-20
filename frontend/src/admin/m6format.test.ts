import { describe, expect, it } from "vitest";
import { dayUserSeries, partialNote, formatEur, formatTokens, groupLimits, limitProblem } from "./m6format";
import type { EditableLimit as Limit, UsageDayUser } from "../api.gen";

const base = { calls: 1, failures: 0, input_tokens: 10, output_tokens: 5, p50_latency_ms: null, cost_eur: 0.5, avg_cost_per_call_eur: 0.5, unpriced_calls: 0 };

describe("m6 format", () => {
  it("formats cost, with a plain message when the price is missing", () => {
    expect(formatEur(null)).toBe("set a price");
    expect(formatEur(0)).toBe("€0.00");
    expect(formatEur(0.0042)).toBe("€0.0042");
    expect(formatEur(1234.5)).toBe("€1,234.50");
  });
  it("shortens tokens", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1500)).toBe("1.5k");
    expect(formatTokens(2_300_000)).toBe("2.3M");
  });
  it("pivots days by person", () => {
    const rows: UsageDayUser[] = [
      { ...base, day: "2026-10-02", name: "Ann", user_id: "a" },
      { ...base, day: "2026-10-01", name: "Ann", user_id: "a" },
      { ...base, day: "2026-10-01", name: "", user_id: null },
    ];
    const s = dayUserSeries(rows, "tokens");
    expect(s.days).toEqual(["2026-10-01", "2026-10-02"]);
    expect(s.series.find((x) => x.name === "Ann")!.data).toEqual([15, 15]);
    expect(s.series.find((x) => x.name === "System")!.data).toEqual([15, 0]);
  });
  it("notes unpriced calls", () => {
    expect(partialNote(0)).toBeNull();
    expect(partialNote(3)).toBe("partial: 3 calls without a price");
  });
  it("groups and checks limits", () => {
    const l = (key: string, group: string): Limit => ({ key, value: 1, default: 1, source: "default", min: 1, max: 10, unit: "", kind: "int", description: "", group });
    expect(groupLimits([l("a", "AI"), l("b", "Data"), l("c", "AI")]).map(([g, x]) => [g, x.length])).toEqual([["AI", 2], ["Data", 1]]);
    expect(limitProblem(l("a", "AI"), "11")).toBe("At most 10.");
    expect(limitProblem(l("a", "AI"), "0")).toBe("At least 1.");
    expect(limitProblem(l("a", "AI"), "")).toBe("Enter a number.");
    expect(limitProblem(l("a", "AI"), "5")).toBeNull();
  });
});
