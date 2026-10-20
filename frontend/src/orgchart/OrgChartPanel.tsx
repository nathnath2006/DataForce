// Owned by agent U1 (docs/M2B-CONTRACT.md section 7.1): org chart with link origins + proposals.
import { useMemo, useState } from "react";
import { useWs } from "../context";
import type { OrgChartNode } from "../types";
import { AiBadge, Confirm, Empty, ErrorNote, Tag, useAction, useLoad } from "../ui";
import { aiApi } from "../assistant/api";
import { orgApi } from "./api";
import {
  aiBadge, buildOverlay, formatEvidence, kindLabel, suggestNotice,
  type ChartNode, type ProposalOut,
} from "./model";
import { OrgChartVisual } from "./OrgChartVisual";
import "./orgchart.css";

function Evidence({ p }: { p: ProposalOut }) {
  const v = formatEvidence(p);
  if (v.kind === "none") return <p className="muted small">No evidence recorded.</p>;
  return (
    <div className="small">
      {v.lines.map((l, i) => <div key={i}>{l}</div>)}
      {v.excerpt && <blockquote>{v.excerpt}</blockquote>}
      {v.managerExcerpt && <div className="muted">Manager named earlier:<blockquote>{v.managerExcerpt}</blockquote></div>}
      {v.meeting && <div className="muted">Meeting: {v.meeting}</div>}
      {v.ai && <div className="muted">{v.ai}</div>}
    </div>
  );
}

function ProposalItem({ p, onDone }: { p: ProposalOut; onDone: () => void }) {
  const { ws } = useWs();
  const act = useAction();
  const [pick, setPick] = useState("");
  const ambiguous = p.manager === null && p.kind === "reports_to";
  const canAccept = !ambiguous || pick !== "";
  const [confirming, setConfirming] = useState<"accept" | "reject" | null>(null);
  return (
    <li className="oc-item">
      <div>
        <strong>{p.contact.full_name}</strong>
        {p.kind === "reports_to"
          ? <> reports to <strong>{p.manager?.full_name ?? "(choose below)"}</strong></>
          : <> is a <strong>{kindLabel(p.kind).toLowerCase()}</strong></>}
        {" "}<Tag kind="mute">suggested</Tag> <Tag>{p.origin === "rule" ? "from rule" : "from meeting"}</Tag>
        {aiBadge(p) && <> <AiBadge>{aiBadge(p)}</AiBadge></>}
        {p.rule && p.origin === "rule" && <span className="muted small"> {p.rule.replace(/_/g, " ")}</span>}
      </div>
      <Evidence p={p} />
      {ambiguous && (
        <fieldset>
          <legend className="small">Several managers fit. Pick one:</legend>
          {p.candidates.map((c) => (
            <label key={c.id} className="check">
              <input type="radio" name={`cand-${p.id}`} value={c.id} checked={pick === c.id} onChange={() => setPick(c.id)} />
              {c.full_name}{c.title ? ` · ${c.title}` : ""}
            </label>
          ))}
        </fieldset>
      )}
      <ErrorNote error={act.error} />
      <div className="row">
        <button className="primary" disabled={act.busy || !canAccept}
          onClick={() => setConfirming("accept")}>Accept</button>
        <button disabled={act.busy} onClick={() => setConfirming("reject")}>Reject</button>
      </div>
      {confirming && (
        <Confirm
          title={confirming === "accept" ? "Accept this suggestion?" : "Reject this suggestion?"}
          confirmLabel={confirming === "accept" ? "Accept" : "Reject"} danger={confirming === "reject"}
          onClose={() => setConfirming(null)}
          onConfirm={() => (confirming === "accept"
            ? orgApi.accept(ws.slug, p.id, ambiguous ? pick : undefined)
            : orgApi.reject(ws.slug, p.id)).then(onDone)}
        >
          <p>{confirming === "accept"
            ? "It becomes a fact in the org chart, keeping its evidence. You can still change the manager by hand later."
            : "It disappears and will not be suggested again for this pair."}</p>
        </Confirm>
      )}
    </li>
  );
}

export function OrgChartPanel(props: {
  accountId: string; nodes: OrgChartNode[]; base: string; onChanged: () => void;
  /** Highlight this contact (contact page). */ current?: string;
  /** Show only these people (manager chain and reports); proposals are still listed. */ only?: Set<string>;
}) {
  const { ws } = useWs();
  const props_ = useLoad(() => orgApi.proposals(ws.slug, props.accountId), [ws.slug, props.accountId]);
  const act = useAction();
  const aiSettings = useLoad(() => aiApi.get(ws.slug), [ws.slug]);
  const useAi = aiSettings.data?.configured === true && aiSettings.data.allow_meeting_org;
  const [msg, setMsg] = useState("");
  const nodes = props.nodes as ChartNode[];
  const open = useMemo(() => (props_.data ?? []).filter((p) => p.status === "proposed" || p.status === "ambiguous"), [props_.data]);
  const shown = useMemo(() => (props.only ? nodes.filter((n) => props.only!.has(n.id)) : nodes), [nodes, props.only]);
  const ov = useMemo(() => buildOverlay(shown, open), [shown, open]);
  const names = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const done = () => { props_.reload(); props.onChanged(); };
  return (
    <div className="stack">
      {ov.tree.length === 0 ? <Empty>No contacts yet.</Empty> : (
        <OrgChartVisual ov={ov} names={names} base={props.base} current={props.current} />
      )}
      <p className="muted small">Solid boxes are links people confirmed. Dashed "suggested" boxes are proposals and are not facts until you accept them.</p>
      <div className="row between wrap">
        <h3>Suggested links ({open.length})</h3>
        <button disabled={act.busy} onClick={() => void act.run(async () => {
          const r = await orgApi.propose(ws.slug, props.accountId, useAi);
          const ai = r.ai ? ` AI: ${r.ai.calls} call(s), ${r.ai.capped} capped, ${r.ai.failed} failed, ${r.ai.dropped} dropped by checks.` : "";
          setMsg(`${r.created} suggestion(s) created, ${r.ambiguous} ambiguous.${ai}`);
          props_.reload();
        })}>Suggest links</button>
      </div>
      {useAi && <p className="muted small">{suggestNotice(aiSettings.data?.provider ?? null, aiSettings.data?.model ?? null)}</p>}
      <ErrorNote error={act.error} />
      <ErrorNote error={props_.error} />
      {msg && <p className="muted small" role="status">{msg}</p>}
      {open.length === 0 ? <Empty>No suggestions. Use "Suggest links" to look for some.</Empty> : (
        <ul className="plain">{open.map((p) => <ProposalItem key={p.id} p={p} onDone={done} />)}</ul>
      )}
    </div>
  );
}
