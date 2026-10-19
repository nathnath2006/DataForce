import { describe, expect, it } from "vitest";
import { aiBadge, buildOverlay, classLabel, meetingOrgNotice, suggestNotice, formatEvidence, originBadge, signalLabel, sourceLabel, type ChartNode, type ProposalOut } from "./model";

const n = (id: string, mgr: string | null): ChartNode => ({ id, full_name: id, title: null, reports_to_id: mgr, source: "manual" });
const ref = (id: string) => ({ id, full_name: id, title: null });
const prop = (id: string, c: string, m: string | null, over: Partial<ProposalOut> = {}): ProposalOut => ({
  id, kind: "reports_to", origin: "rule", rule: "c_level_to_ceo", status: "proposed", contact: ref(c),
  manager: m ? ref(m) : null, candidates: [], evidence: null, created_at: "", decided_at: null, ...over,
});

describe("buildOverlay", () => {
  const nodes = [n("a", null), n("b", "a"), n("c", null), n("d", null)];
  it("keeps suggested edges out of the fact tree", () => {
    const o = buildOverlay(nodes, [prop("p1", "c", "a")]);
    expect(o.tree.map((t) => t.node.id)).toEqual(["a", "c", "d"]);
    expect(o.tree[0]!.children.map((t) => t.node.id)).toEqual(["b"]);
    expect(o.suggestedByManager.get("a")?.map((s) => s.contactId)).toEqual(["c"]);
  });
  it("drops cycles to the list", () => {
    const o = buildOverlay(nodes, [prop("p1", "a", "b")]);
    expect(o.suggestedByManager.size).toBe(0);
    expect(o.listOnly).toHaveLength(1);
  });
  it("catches cycles among suggestions", () => {
    const o = buildOverlay(nodes, [prop("p1", "c", "d"), prop("p2", "d", "c")]);
    expect(o.suggestedByManager.size).toBe(1);
    expect(o.listOnly.map((p) => p.id)).toEqual(["p2"]);
  });
  it("lists ambiguous, signal, decided and linked-contact proposals without drawing", () => {
    const o = buildOverlay(nodes, [
      prop("amb", "c", null, { status: "ambiguous" }), prop("sig", "c", null, { kind: "champion" }),
      prop("rej", "c", "a", { status: "rejected" }), prop("has", "b", "c"), prop("self", "c", "c"),
    ]);
    expect(o.suggestedByManager.size).toBe(0);
    expect(o.listOnly.map((p) => p.id)).toEqual(["amb", "sig", "has", "self"]);
  });
});

describe("labels", () => {
  it("maps badges", () => {
    expect(originBadge("rule")).toBe("from rule");
    expect(originBadge("meeting")).toBe("from meeting");
    expect(originBadge("manual")).toBeNull();
    expect(signalLabel("decision_maker")).toBe("Decision maker");
    expect(sourceLabel("llm")).toBe("AI");
    expect(sourceLabel(null)).toBe("unknown");
    expect(classLabel("sales", "c_level")).toBe("sales · c level");
    expect(classLabel(null, "unknown")).toBe("unknown · unknown");
  });
});

describe("formatEvidence manager quote", () => {
  it("shows the manager quote as text only, and null without it", () => {
    const v = formatEvidence({ origin: "meeting", rule: null, evidence: { excerpt: "I report there.", manager_excerpt: "<i>Ann</i> runs sales." } });
    expect(v.managerExcerpt).toBe("<i>Ann</i> runs sales.");
    expect(formatEvidence({ origin: "meeting", rule: null, evidence: { excerpt: "x" } }).managerExcerpt).toBeNull();
    expect(formatEvidence({ origin: "rule", rule: null, evidence: null }).managerExcerpt).toBeNull();
  });
});

describe("formatEvidence", () => {
  it("formats rule evidence", () => {
    const v = formatEvidence({ origin: "rule", rule: "x", evidence: { contact_title: "CFO", manager_title: "CEO", explanation: "Because." } });
    expect(v.kind).toBe("rule");
    expect(v.lines).toEqual(["Contact title: CFO", "Manager title: CEO", "Because."]);
  });
  it("keeps meeting excerpt as plain text", () => {
    const v = formatEvidence({ origin: "meeting", rule: null, evidence: { excerpt: "<b>I report to Ann</b>", speaker: "Bob", meeting_title: "Kickoff", meeting_date: "2026-01-02" } });
    expect(v.excerpt).toBe("<b>I report to Ann</b>");
    expect(v.meeting).toBe("Kickoff, 2026-01-02");
  });
  it("says when the transcript behind a decided suggestion was deleted", () => {
    const v = formatEvidence({ origin: "meeting", rule: null, evidence: { document_deleted: true, meeting_title: "Kickoff" } });
    expect(v.excerpt).toBeNull();
    expect(v.lines).toEqual(["The transcript was deleted, so the quote is gone."]);
  });
  it("handles missing evidence", () => {
    expect(formatEvidence({ origin: "rule", rule: null, evidence: null }).kind).toBe("none");
  });
});

describe("found by AI", () => {
  const ai = { found_by: "ai", provider: "gemini", model: "gemini-2.5-flash", excerpt: "Ann is my boss", speaker: "Bob" };
  it("tags proposals the AI pass found, and only those", () => {
    expect(aiBadge({ evidence: ai })).toBe("found by AI");
    expect(aiBadge({ evidence: { excerpt: "x", pattern: "en_i_report_to" } })).toBeNull();
    expect(aiBadge({ evidence: null })).toBeNull();
  });
  it("shows provider and model in the evidence, not for patterns", () => {
    expect(formatEvidence({ origin: "meeting", rule: "ai", evidence: ai }).ai).toBe("found by AI · gemini · gemini-2.5-flash");
    expect(formatEvidence({ origin: "meeting", rule: "x", evidence: { excerpt: "x" } }).ai).toBeNull();
    expect(formatEvidence({ origin: "rule", rule: null, evidence: null }).ai).toBeNull();
  });
  it("says what is sent", () => {
    expect(meetingOrgNotice("gemini", "gemini-2.5-flash")).toBe(
      "Sends the sentences that name one of the account's contacts, speak about the project in the first person, or contain an org or decision phrase, with the account's contact names, to gemini gemini-2.5-flash. Full transcripts are never sent. Off by default.");
    expect(suggestNotice("anthropic", "claude-haiku-5-5")).toContain("anthropic claude-haiku-5-5");
  });
});
