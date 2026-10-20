import { Link } from "react-router";
import type { OrgTreeNode } from "../lib";
import { Tag } from "../ui";
import { originBadge, signalKind, signalLabel, type ChartNode, type Overlay } from "./model";

const SENIORITY: Record<string, string> = {
  c_level: "C-level", vp: "VP", director: "Director", manager: "Manager", senior: "Senior", ic: "IC",
  individual_contributor: "IC", junior: "Junior", intern: "Intern", owner: "Owner", partner: "Partner", head: "Head",
};
export function seniorityBadge(s: string | null | undefined): string | null {
  if (!s || s === "unknown") return null;
  return SENIORITY[s] ?? s.replace(/_/g, " ");
}

function PersonNode(p: { n: ChartNode; base: string; current: boolean; suggested?: boolean; orphan?: boolean; onEvidence?: () => void }) {
  const { n } = p;
  const sen = seniorityBadge(n.title_seniority);
  const origin = originBadge(n.link_origin);
  return (
    <Link to={`${p.base}/contacts/${n.id}`}
      className={`ocv-node${p.current ? " current" : ""}${p.suggested ? " suggested" : ""}`}
      aria-current={p.current ? "true" : undefined}
      aria-label={`${n.full_name}${n.title ? `, ${n.title}` : ""}${p.suggested ? ", suggested link, not confirmed" : ""}`}>
      <span className="ocv-name">{n.full_name}</span>
      <span className="ocv-title">{n.title ?? "No title"}</span>
      <span className="ocv-badges">
        {sen && <span className="ocv-sen">{sen}</span>}
        {p.suggested && <Tag kind="mute">suggested</Tag>}
        {!p.suggested && origin && <Tag kind="ok">{origin}</Tag>}
        {p.orphan && <Tag kind="warn">manager not in chart</Tag>}
        {(n.signals ?? []).map((s) => <Tag key={s} kind={signalKind(s)}>{signalLabel(s)}</Tag>)}
      </span>
    </Link>
  );
}

function Branch(p: { t: OrgTreeNode; base: string; ov: Overlay; names: Map<string, ChartNode>; current?: string }) {
  const n = p.names.get(p.t.node.id) ?? (p.t.node as ChartNode);
  const sugg = p.ov.suggestedByManager.get(n.id) ?? [];
  const hasKids = p.t.children.length > 0 || sugg.length > 0;
  return (
    <li>
      <PersonNode n={n} base={p.base} current={n.id === p.current} orphan={p.t.orphan} />
      {hasKids && (
        <ul>
          {p.t.children.map((c) => <Branch key={c.node.id} {...p} t={c} />)}
          {sugg.map((s) => {
            const sn = p.names.get(s.contactId);
            return sn ? <li key={s.proposalId}><PersonNode n={sn} base={p.base} current={sn.id === p.current} suggested /></li> : null;
          })}
        </ul>
      )}
    </li>
  );
}

/** Visual chart: boxes with connectors; every box is a link to the contact. Scrolls sideways when wide. */
export function OrgChartVisual(p: { ov: Overlay; names: Map<string, ChartNode>; base: string; current?: string }) {
  return (
    <div className="ocv" role="region" aria-label="Org chart" tabIndex={-1}>
      <ul className="ocv-root">
        {p.ov.tree.map((t) => <Branch key={t.node.id} t={t} base={p.base} ov={p.ov} names={p.names} current={p.current} />)}
      </ul>
    </div>
  );
}
