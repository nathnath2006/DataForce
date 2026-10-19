import { useEffect, useState } from "react";
import { useWs } from "../context";
import { flowApi } from "../flows/flowApi";
import type { FlowSummary } from "../flows/types";
import { useLoad } from "../ui";
import type { Source } from "./types";

export const CRM_TABLES = ["deals", "accounts", "contacts", "companies", "meetings", "meeting_themes", "deal_theme_flags", "activities", "stage_events", "tasks"];

interface NodeOpt { id: string; label: string }

export function SourcePicker(props: { value: Source; onChange: (s: Source) => void }) {
  const { ws } = useWs();
  const { value } = props;
  const flows = useLoad<FlowSummary[]>(() => (value.kind === "flow" ? flowApi.list(ws.slug) : Promise.resolve([])), [ws.slug, value.kind]);
  const [nodes, setNodes] = useState<NodeOpt[]>([]);
  const flowId = value.kind === "flow" ? value.flow_id : "";
  useEffect(() => {
    if (!flowId) { setNodes([]); return; }
    let live = true;
    flowApi.get(ws.slug, flowId).then(
      (f) => { if (live) setNodes(f.graph.nodes.map((n) => ({ id: n.id, label: `${n.label ?? n.config.type} (${n.id})` }))); },
      () => { if (live) setNodes([]); },
    );
    return () => { live = false; };
  }, [ws.slug, flowId]);
  const sel = value.kind === "crm" ? `crm:${value.table}` : "flow";
  return (
    <div className="stack wb-source">
      <label>Source
        <select value={sel} onChange={(e) => {
          const v = e.target.value;
          if (v === "flow") props.onChange({ kind: "flow", flow_id: "", node_id: "" });
          else props.onChange({ kind: "crm", table: v.slice(4) });
        }}>
          {CRM_TABLES.map((t) => <option key={t} value={`crm:${t}`}>CRM: {t}</option>)}
          <option value="flow">A flow block…</option>
        </select>
      </label>
      {value.kind === "flow" && (
        <>
          <select aria-label="Flow" value={value.flow_id} onChange={(e) => props.onChange({ kind: "flow", flow_id: e.target.value, node_id: "" })}>
            <option value="">Choose a flow</option>
            {(flows.data ?? []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
          <select aria-label="Block" value={value.node_id} disabled={!value.flow_id}
            onChange={(e) => props.onChange({ ...value, node_id: e.target.value })}>
            <option value="">Choose a block</option>
            {nodes.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
          </select>
        </>
      )}
    </div>
  );
}

/** A flow source is usable only once both ids are chosen. */
export function sourceReady(s: Source): boolean { return s.kind === "crm" || (!!s.flow_id && !!s.node_id); }
