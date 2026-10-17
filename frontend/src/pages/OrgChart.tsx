import { useMemo } from "react";
import { Link } from "react-router";
import { buildOrgTree, type OrgTreeNode } from "../lib";
import type { OrgChartNode } from "../types";
import { Empty, Tag } from "../ui";

function Branch({ t, base }: { t: OrgTreeNode; base: string }) {
  return (
    <li>
      <Link to={`${base}/contacts/${t.node.id}`}>{t.node.full_name}</Link>
      {t.node.title && <span className="muted"> · {t.node.title}</span>}
      {t.orphan && <> <Tag kind="warn">manager not in chart</Tag></>}
      {t.node.source !== "manual" && <> <Tag kind="mute">{t.node.source}</Tag></>}
      {t.children.length > 0 && <ul>{t.children.map((c) => <Branch key={c.node.id} t={c} base={base} />)}</ul>}
    </li>
  );
}

export function OrgChart({ nodes, base }: { nodes: OrgChartNode[]; base: string }) {
  const tree = useMemo(() => buildOrgTree(nodes), [nodes]);
  if (tree.length === 0) return <Empty>No contacts yet.</Empty>;
  return <ul className="tree">{tree.map((t) => <Branch key={t.node.id} t={t} base={base} />)}</ul>;
}
