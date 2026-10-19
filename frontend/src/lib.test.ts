import { describe, expect, it } from "vitest";
import {
  ApiError, buildOrgTree, formatDate, formatDiffWithCi, formatEur, formatPct, formatPts, formatStat,
  formatWithCi, isSafeAuthorizeUrl, parseApiError, segmentLabel, tamtamReason,
} from "./lib";
import type { OrgChartNode, StatValue } from "./types";

const n = (id: string, mgr: string | null): OrgChartNode => ({
  id, full_name: id, title: null, reports_to_id: mgr, source: "manual",
});
const ids = (t: { node: OrgChartNode; children: unknown[] }[]) => t.map((x) => x.node.id);

describe("buildOrgTree", () => {
  it("builds roots and nested children", () => {
    const t = buildOrgTree([n("c", "b"), n("b", "a"), n("a", null), n("d", "a")]);
    expect(ids(t)).toEqual(["a"]);
    const a = t[0]!;
    expect(ids(a.children)).toEqual(["b", "d"]);
    expect(ids(a.children[0]!.children)).toEqual(["c"]);
    expect(a.orphan).toBe(false);
  });
  it("treats a missing manager as an orphan root", () => {
    const t = buildOrgTree([n("a", null), n("x", "ghost")]);
    expect(ids(t)).toEqual(["a", "x"]);
    expect(t[1]!.orphan).toBe(true);
    expect(t[0]!.orphan).toBe(false);
  });
  it("is safe on cycles and self references: every node once", () => {
    const t = buildOrgTree([n("a", "b"), n("b", "a"), n("s", "s"), n("r", null)]);
    const all: string[] = [];
    const walk = (l: ReturnType<typeof buildOrgTree>) => l.forEach((x) => { all.push(x.node.id); walk(x.children); });
    walk(t);
    expect(all.sort()).toEqual(["a", "b", "r", "s"]);
  });
  it("handles empty input", () => expect(buildOrgTree([])).toEqual([]));
});

describe("formatting", () => {
  it("formats EUR", () => {
    expect(formatEur(12345)).toContain("12,345");
    expect(formatEur("1500.50", true)).toContain("1,500.50");
    expect(formatEur(null)).toBe("—");
  });
  it("formats percentages and points", () => {
    expect(formatPct(0.4567)).toBe("45.7%");
    expect(formatPts(0.123)).toBe("+12.3 pts");
    expect(formatPts(-0.05)).toBe("−5.0 pts");
    expect(formatPct(null)).toBe("—");
  });
  it("shows the CI next to the value", () => {
    expect(formatWithCi(0.5, 0.4, 0.6, "rate")).toBe("50.0% (95% CI 40.0% to 60.0%)");
    expect(formatWithCi(0.5, null, null, "rate")).toBe("50.0%");
    expect(formatDiffWithCi(0.2, 0.1, 0.3, "rate")).toBe("+20.0 pts (95% CI +10.0 pts to +30.0 pts)");
    const s = { metric: "cycle_days", value: 30, ci_low: 25, ci_high: 36, n: 10, method: "x",
      status: "verified", reasons: [], details: {} } as StatValue;
    expect(formatStat(s)).toBe("30 d (95% CI 25 d to 36 d)");
  });
});

describe("isSafeAuthorizeUrl", () => {
  const iss = "https://api.tamtam.ai";
  it("accepts https on the issuer origin", () => {
    expect(isSafeAuthorizeUrl("https://api.tamtam.ai/authorize?x=1", iss)).toBe(true);
    expect(isSafeAuthorizeUrl("https://api.tamtam.ai/authorize", `${iss}/`)).toBe(true);
  });
  it("refuses other origins, http, junk and a missing issuer", () => {
    expect(isSafeAuthorizeUrl("https://evil.example/authorize", iss)).toBe(false);
    expect(isSafeAuthorizeUrl("https://api.tamtam.ai.evil.example/a", iss)).toBe(false);
    expect(isSafeAuthorizeUrl("https://user@evil.example/", iss)).toBe(false);
    expect(isSafeAuthorizeUrl("http://api.tamtam.ai/authorize", "http://api.tamtam.ai")).toBe(false);
    expect(isSafeAuthorizeUrl("javascript:alert(1)", iss)).toBe(false);
    expect(isSafeAuthorizeUrl("not a url", iss)).toBe(false);
    expect(isSafeAuthorizeUrl("https://api.tamtam.ai/a", null)).toBe(false);
  });
});

describe("parseApiError", () => {
  it("reads the error envelope", () => {
    const e = parseApiError(409, { error: { code: "paid_lookup_refused", message: "no" } });
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(409);
    expect(e.code).toBe("paid_lookup_refused");
    expect(e.message).toBe("no");
  });
  it("falls back on malformed bodies", () => {
    for (const body of [null, "x", {}, { error: "x" }, { error: { code: 1, message: 2 } }]) {
      const e = parseApiError(500, body);
      expect(e.code).toBe("http_error");
      expect(e.message).toContain("500");
    }
  });
});

describe("review fixes", () => {
  it("refuses userinfo in the authorize URL or the issuer (SR8-02)", () => {
    expect(isSafeAuthorizeUrl("https://user:pw@api.tamtam.ai/authorize", "https://api.tamtam.ai")).toBe(false);
    expect(isSafeAuthorizeUrl("https://api.tamtam.ai/authorize", "https://u@api.tamtam.ai")).toBe(false);
    expect(isSafeAuthorizeUrl("https://api.tamtam.ai/authorize?x=1", "https://api.tamtam.ai")).toBe(true);
  });
  it("maps callback reasons from a fixed list only (SR8-01)", () => {
    expect(tamtamReason("denied")).toMatch(/denied/);
    for (const r of ["__proto__", "constructor", "toString", "<b>x</b>", null]) {
      expect(tamtamReason(r)).toBe("Try again.");
    }
  });
  it("labels segments", () => {
    expect(segmentLabel("smb")).toBe("SMB");
    expect(segmentLabel("midmarket")).toBe("Mid-market");
    expect(segmentLabel(null)).toBe("—");
  });
});

describe("formatDate", () => {
  it("formats a calendar date in en-GB", () => {
    expect(formatDate("2026-10-18")).toBe("18 Oct 2026");
    expect(formatDate(null)).toBe("—");
  });
});
