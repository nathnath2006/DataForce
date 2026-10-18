// Pure logic for the org chart panel (U1): proposals overlay, labels, evidence formatting.
import { buildOrgTree, type OrgTreeNode } from "../lib";
import type { OrgChartNode } from "../types";

export type LinkOrigin = "manual" | "rule" | "meeting";
export type ProposalKind = "reports_to" | "champion" | "blocker" | "decision_maker";
export type ProposalStatus = "proposed" | "ambiguous" | "accepted" | "rejected";

export interface ChartNode extends OrgChartNode {
  title_function?: string | null; title_seniority?: string | null;
  link_origin?: LinkOrigin | null; link_proposal_id?: string | null; signals?: string[];
}
export interface PersonRef { id: string; full_name: string; title: string | null }
export interface ProposalOut {
  id: string; kind: ProposalKind; origin: "rule" | "meeting"; rule: string | null; status: ProposalStatus;
  contact: PersonRef; manager: PersonRef | null; candidates: PersonRef[];
  evidence: Record<string, unknown> | null; created_at: string; decided_at: string | null;
}

export interface SuggestedEdge { proposalId: string; contactId: string; managerId: string; ambiguous: false }
export interface Overlay {
  tree: OrgTreeNode[];
  /** Suggested edges by manager id: never part of `tree`. */
  suggestedByManager: Map<string, SuggestedEdge[]>;
  /** Proposals that cannot be drawn as one edge (ambiguous, signals, unusable). */
  listOnly: ProposalOut[];
}

function descendants(tree: OrgTreeNode[], id: string): Set<string> {
  const out = new Set<string>();
  const walk = (t: OrgTreeNode, inside: boolean) => {
    const here = inside || t.node.id === id;
    if (inside) out.add(t.node.id);
    for (const c of t.children) walk(c, here);
  };
  for (const r of tree) walk(r, false);
  return out;
}

/** Fact tree (from real links only) plus the open reports_to proposals, kept apart and cycle-safe. */
export function buildOverlay(nodes: ChartNode[], proposals: ProposalOut[]): Overlay {
  const tree = buildOrgTree(nodes);
  const ids = new Set(nodes.map((n) => n.id));
  const hasManager = new Map(nodes.map((n) => [n.id, n.reports_to_id !== null]));
  const suggestedByManager = new Map<string, SuggestedEdge[]>();
  const listOnly: ProposalOut[] = [];
  // Accepted suggestions in this overlay count as edges for cycle checks.
  const extra = new Map<string, string>();
  for (const p of proposals) {
    if (p.status !== "proposed" && p.status !== "ambiguous") continue;
    const m = p.manager;
    const drawable = p.kind === "reports_to" && p.status === "proposed" && m !== null
      && ids.has(p.contact.id) && ids.has(m.id) && m.id !== p.contact.id && hasManager.get(p.contact.id) === false;
    if (!drawable || m === null) { listOnly.push(p); continue; }
    let cyc = descendants(tree, p.contact.id).has(m.id);
    for (let cur: string | undefined = m.id, i = 0; !cyc && cur !== undefined && i < 1000; i++) {
      cur = extra.get(cur);
      if (cur === p.contact.id) cyc = true;
    }
    if (cyc) { listOnly.push(p); continue; }
    extra.set(p.contact.id, m.id);
    const l = suggestedByManager.get(m.id) ?? [];
    l.push({ proposalId: p.id, contactId: p.contact.id, managerId: m.id, ambiguous: false });
    suggestedByManager.set(m.id, l);
  }
  return { tree, suggestedByManager, listOnly };
}

// ---- labels ----
export function originBadge(o: LinkOrigin | null | undefined): string | null {
  return o === "rule" ? "from rule" : o === "meeting" ? "from meeting" : null;
}
/** "found by AI" tag text for a proposal whose evidence says the AI pass found it, else null. */
export function aiBadge(p: Pick<ProposalOut, "evidence">): string | null {
  return p.evidence?.found_by === "ai" ? "found by AI" : null;
}
/** What the AI pass sends (Settings checkbox text). */
export function meetingOrgNotice(provider: string | null, model: string | null): string {
  return `Sends only sentences that name one of the account's contacts or contain an org phrase, with the account's contact names, to ${provider ?? "the provider"} ${model ?? "model"}. Full transcripts are never sent. Off by default.`;
}
/** Under "Suggest links" when the switch is on. */
export function suggestNotice(provider: string | null, model: string | null): string {
  return `AI is on: candidate sentences from meetings and the contact names are sent to ${provider ?? "the provider"} ${model ?? "model"}. Every suggestion is checked against the transcript and still needs your approval.`;
}
const SIGNALS = new Map([["champion", "Champion"], ["blocker", "Blocker"], ["decision_maker", "Decision maker"]]);
export function signalLabel(s: string): string { return SIGNALS.get(s) ?? s.replace(/_/g, " "); }
export function signalKind(s: string): "ok" | "bad" | "warn" { return s === "champion" ? "ok" : s === "blocker" ? "bad" : "warn"; }
const SOURCES = new Map([["dictionary", "dictionary"], ["llm", "AI"], ["manual", "manual"]]);
export function sourceLabel(s: string | null | undefined): string { return (s && SOURCES.get(s)) || "unknown"; }
export function classLabel(fn: string | null | undefined, sen: string | null | undefined): string {
  const f = (x: string | null | undefined) => (!x || x === "unknown" ? "unknown" : x.replace(/_/g, " "));
  return `${f(fn)} · ${f(sen)}`;
}
const KINDS = new Map([["reports_to", "Reports to"], ["champion", "Champion"], ["blocker", "Blocker"], ["decision_maker", "Decision maker"]]);
export function kindLabel(k: string): string { return KINDS.get(k) ?? k; }

// ---- evidence ----
export interface EvidenceView {
  kind: "rule" | "meeting" | "none";
  lines: string[];
  excerpt: string | null;
  meeting: string | null;
  /** "found by AI" when the AI pass found it (with provider and model), else null. */
  ai: string | null;
}
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);

/** Turn raw evidence JSON into plain text pieces. Everything is text, never markup. */
export function formatEvidence(p: Pick<ProposalOut, "origin" | "evidence" | "rule">): EvidenceView {
  const ev = p.evidence ?? {};
  if (p.origin === "meeting") {
    const title = str(ev.meeting_title) ?? str(ev.document_title);
    const date = str(ev.meeting_date);
    const meeting = [title, date].filter(Boolean).join(", ") || null;
    const speaker = str(ev.speaker);
    const lines = speaker ? [`Said by ${speaker}`] : [];
    if (ev.document_deleted === true) lines.push("The transcript was deleted, so the quote is gone.");
    const by = ev.found_by === "ai" ? ["found by AI", str(ev.provider), str(ev.model)].filter(Boolean).join(" · ") : null;
    return { kind: "meeting", lines, excerpt: str(ev.excerpt), meeting, ai: by };
  }
  const lines: string[] = [];
  const ct = str(ev.contact_title), mt = str(ev.manager_title);
  if (ct) lines.push(`Contact title: ${ct}${str(ev.contact_class) ? ` (${str(ev.contact_class)})` : ""}`);
  if (mt) lines.push(`Manager title: ${mt}${str(ev.manager_class) ? ` (${str(ev.manager_class)})` : ""}`);
  const ex = str(ev.explanation);
  if (ex) lines.push(ex);
  if (p.rule === "contradicts_current_link") lines.push("This contradicts the current link.");
  return { kind: lines.length ? "rule" : "none", lines, excerpt: null, meeting: null, ai: null };
}
