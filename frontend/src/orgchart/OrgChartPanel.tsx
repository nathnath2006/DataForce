// Owned by agent U1 (docs/M2B-CONTRACT.md section 7.1): org chart with link origins + proposals.
import type { OrgChartNode } from "../types";
import { OrgChart } from "../pages/OrgChart";

export function OrgChartPanel(props: { accountId: string; nodes: OrgChartNode[]; base: string; onChanged: () => void }) {
  void props.accountId; void props.onChanged;
  return <OrgChart nodes={props.nodes} base={props.base} />;
}
