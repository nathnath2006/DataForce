import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { formatEur, label } from "../lib";
import { DEAL_STAGES, LEAD_SOURCES, type DealOut, type DealStage, type LeadSource } from "../types";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Tag, emptyToNull, todayIso, useAction, useDebounced, useLoad } from "../ui";

const isClosed = (s: DealStage) => s === "closed_won" || s === "closed_lost";

export function DealsPage() {
  const { ws, users } = useWs();
  const [f, setF] = useState({ stage: "", lead_source: "", owner_id: "", q: "" });
  const dq = useDebounced(f.q);
  const { data, error, loading, reload } = useLoad(
    () => api.listDeals(ws.slug, { stage: f.stage, lead_source: f.lead_source, owner_id: f.owner_id, q: dq, limit: 1000 }),
    [ws.slug, f.stage, f.lead_source, f.owner_id, dq]);
  const [editing, setEditing] = useState<DealOut | "new" | null>(null);
  const [closing, setClosing] = useState<{ deal: DealOut; stage: DealStage } | null>(null);
  const [deleting, setDeleting] = useState<DealOut | null>(null);
  const act = useAction();
  const changeStage = (d: DealOut, stage: DealStage) => {
    if (stage === d.stage) return;
    if (isClosed(stage)) { setClosing({ deal: d, stage }); return; }
    void act.run(async () => { await api.setStage(ws.slug, d.id, { stage }); reload(); });
  };
  return (
    <section>
      <div className="row between wrap">
        <h1>Deals</h1>
        <button className="primary" onClick={() => setEditing("new")}>New deal</button>
      </div>
      <div className="row wrap filters">
        <input type="search" placeholder="Search deal name" aria-label="Search" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <select aria-label="Stage" value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}>
          <option value="">All stages</option>{DEAL_STAGES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <select aria-label="Lead source" value={f.lead_source} onChange={(e) => setF({ ...f, lead_source: e.target.value })}>
          <option value="">All sources</option>{LEAD_SOURCES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <select aria-label="Owner" value={f.owner_id} onChange={(e) => setF({ ...f, owner_id: e.target.value })}>
          <option value="">All owners</option>{users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
        </select>
        {data && <span className="muted">{data.items.length} of {data.total}</span>}
      </div>
      <ErrorNote error={error} /><ErrorNote error={act.error} />
      {loading && !data ? <Loading /> : data && data.items.length === 0 ? <Empty>No deals match.</Empty> : data && (
        <div className="tablewrap"><table>
          <thead><tr><th>Deal</th><th>Account</th><th>Stage</th><th className="num">Amount</th><th>Source</th><th>Owner</th><th>Created</th><th>Closed</th><th className="num">Cycle (d)</th><th></th></tr></thead>
          <tbody>{data.items.map((d) => (
            <tr key={d.id}>
              <td><button className="link" onClick={() => setEditing(d)}>{d.name}</button></td>
              <td><Link to={`/w/${ws.slug}/accounts/${d.account_id}`}>{d.account_name}</Link></td>
              <td>
                <select aria-label={`Stage of ${d.name}`} value={d.stage} onChange={(e) => changeStage(d, e.target.value as DealStage)}>
                  {DEAL_STAGES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
                </select>
              </td>
              <td className="num">{formatEur(d.amount_eur)}</td>
              <td>{d.lead_source ? <Tag>{label(d.lead_source)}</Tag> : "—"}</td>
              <td>{d.owner_name ?? "—"}</td><td>{d.created_on}</td><td>{d.closed_on ?? "—"}</td>
              <td className="num">{d.cycle_days ?? "—"}</td>
              <td><button className="link" onClick={() => setDeleting(d)}>Delete</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {editing && <DealForm deal={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} onSaved={reload} />}
      {closing && <CloseDialog {...closing} onClose={() => setClosing(null)} onDone={reload} />}
      {deleting && (
        <Confirm title="Delete deal" confirmLabel="Delete" danger onClose={() => setDeleting(null)}
          onConfirm={async () => { await api.deleteDeal(ws.slug, deleting.id); reload(); }}>
          <p>Delete “{deleting.name}”? Deals are removed permanently.</p>
        </Confirm>
      )}
    </section>
  );
}

function CloseDialog(props: { deal: DealOut; stage: DealStage; onClose: () => void; onDone: () => void }) {
  const { ws } = useWs();
  const [on, setOn] = useState(todayIso());
  const a = useAction();
  return (
    <Modal title={`Mark as ${label(props.stage).toLowerCase()}`} onClose={props.onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void a.run(async () => { await api.setStage(ws.slug, props.deal.id, { stage: props.stage, closed_on: on }); props.onDone(); props.onClose(); });
      }}>
        <Field label="Closed on"><input type="date" value={on} min={props.deal.created_on} onChange={(e) => setOn(e.target.value)} required /></Field>
        <ErrorNote error={a.error} />
        <div className="row end"><button type="button" onClick={props.onClose}>Cancel</button><button className="primary" disabled={a.busy || !on}>Close deal</button></div>
      </form>
    </Modal>
  );
}

function DealForm(props: { deal?: DealOut; onClose: () => void; onSaved: () => void }) {
  const { ws, users, actingAs } = useWs();
  const d0 = props.deal;
  const accounts = useLoad(() => api.listAccounts(ws.slug, { limit: 1000 }), [ws.slug]);
  const [f, setF] = useState({
    name: d0?.name ?? "", account_id: d0?.account_id ?? "", amount: d0?.amount_eur?.toString() ?? "",
    lead_source: (d0?.lead_source ?? "") as LeadSource | "", owner_id: d0?.owner_id ?? actingAs ?? "",
    created_on: d0?.created_on ?? todayIso(), stage: "prospecting" as DealStage, closed_on: todayIso(), lost_reason: d0?.lost_reason ?? "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const a = useAction();
  const amount = f.amount.trim() === "" ? null : f.amount.trim();
  return (
    <Modal title={d0 ? "Edit deal" : "New deal"} onClose={props.onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void a.run(async () => {
          if (d0) {
            await api.updateDeal(ws.slug, d0.id, {
              name: f.name.trim(), amount_eur: amount, lead_source: f.lead_source || null,
              owner_id: f.owner_id || null, created_on: f.created_on, lost_reason: emptyToNull(f.lost_reason),
            });
          } else {
            await api.createDeal(ws.slug, {
              account_id: f.account_id, name: f.name.trim(), amount_eur: amount, stage: f.stage,
              lead_source: f.lead_source || null, owner_id: f.owner_id || null, created_on: f.created_on,
              closed_on: isClosed(f.stage) ? f.closed_on : null, lost_reason: emptyToNull(f.lost_reason),
            });
          }
          props.onSaved();
          props.onClose();
        });
      }}>
        <Field label="Name"><input value={f.name} onChange={set("name")} required maxLength={300} autoFocus /></Field>
        {!d0 && (
          <Field label="Account">
            <select value={f.account_id} onChange={set("account_id")} required>
              <option value="">Choose…</option>{accounts.data?.items.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </Field>
        )}
        <div className="grid2">
          <Field label="Amount (EUR)"><input type="number" min={0} step="0.01" value={f.amount} onChange={set("amount")} /></Field>
          <Field label="Lead source">
            <select value={f.lead_source} onChange={set("lead_source")}><option value="">—</option>{LEAD_SOURCES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select>
          </Field>
          <Field label="Owner">
            <select value={f.owner_id} onChange={set("owner_id")}><option value="">—</option>{users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}</select>
          </Field>
          <Field label="Created on"><input type="date" value={f.created_on} onChange={set("created_on")} required /></Field>
          {!d0 && (
            <Field label="Stage"><select value={f.stage} onChange={set("stage")}>{DEAL_STAGES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></Field>
          )}
          {!d0 && isClosed(f.stage) && <Field label="Closed on"><input type="date" value={f.closed_on} min={f.created_on} onChange={set("closed_on")} required /></Field>}
        </div>
        <Field label="Lost reason"><input value={f.lost_reason} onChange={set("lost_reason")} maxLength={500} /></Field>
        {d0 && <p className="muted small">Change the stage from the list.</p>}
        <ErrorNote error={a.error} />
        <div className="row end"><button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy || f.name.trim() === "" || (!d0 && f.account_id === "")}>Save</button></div>
      </form>
    </Modal>
  );
}
