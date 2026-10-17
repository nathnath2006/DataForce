import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { label } from "../lib";
import { SEGMENTS, type AccountCreate, type AccountOut, type Segment } from "../types";
import { Empty, ErrorNote, Field, Loading, Modal, Tag, emptyToNull, useAction, useDebounced, useLoad } from "../ui";

export function AccountsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [segment, setSegment] = useState("");
  const dq = useDebounced(q);
  const [creating, setCreating] = useState(false);
  const { data, error, loading } = useLoad(
    () => api.listAccounts(ws.slug, { q: dq, segment, limit: 1000 }), [ws.slug, dq, segment]);
  return (
    <section>
      <div className="row between wrap">
        <h1>Accounts</h1>
        <button className="primary" onClick={() => setCreating(true)}>New account</button>
      </div>
      <div className="row wrap filters">
        <input type="search" placeholder="Search name or domain" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Segment" value={segment} onChange={(e) => setSegment(e.target.value)}>
          <option value="">All segments</option>
          {SEGMENTS.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        {data && <span className="muted">{data.items.length} of {data.total}</span>}
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data && data.items.length === 0 ? <Empty>No accounts match.</Empty> : data && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>Name</th><th>Industry</th><th>Segment</th><th>Region</th><th className="num">Contacts</th><th className="num">Open deals</th></tr></thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id}>
                  <td><Link to={a.id}>{a.name}</Link>{a.domain && <div className="muted small">{a.domain}</div>}</td>
                  <td>{a.industry ?? "—"}</td>
                  <td>{a.segment ? <Tag>{label(a.segment)}</Tag> : "—"}</td>
                  <td>{a.region ?? "—"}</td>
                  <td className="num">{a.n_contacts}</td>
                  <td className="num">{a.n_open_deals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <AccountForm onClose={() => setCreating(false)} onSaved={(a) => nav(a.id)} />}
    </section>
  );
}

export function AccountForm(props: { account?: AccountOut; onClose: () => void; onSaved: (a: AccountOut) => void }) {
  const { ws } = useWs();
  const a0 = props.account;
  const [f, setF] = useState({
    name: a0?.name ?? "", domain: a0?.domain ?? "", industry: a0?.industry ?? "", segment: (a0?.segment ?? "") as Segment | "",
    employee_count: a0?.employee_count?.toString() ?? "", region: a0?.region ?? "", country: a0?.country ?? "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const act = useAction();
  const submit = () => act.run(async () => {
    const body: AccountCreate = {
      name: f.name.trim(), domain: emptyToNull(f.domain), industry: emptyToNull(f.industry),
      segment: f.segment === "" ? null : f.segment,
      employee_count: f.employee_count.trim() === "" ? null : Number(f.employee_count),
      region: emptyToNull(f.region), country: emptyToNull(f.country)?.toUpperCase() ?? null,
    };
    const saved = a0 ? await api.updateAccount(ws.slug, a0.id, body) : await api.createAccount(ws.slug, body);
    props.onSaved(saved);
    props.onClose();
  });
  return (
    <Modal title={a0 ? "Edit account" : "New account"} onClose={props.onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <Field label="Name"><input value={f.name} onChange={set("name")} required maxLength={300} autoFocus /></Field>
        <Field label="Domain"><input value={f.domain} onChange={set("domain")} maxLength={253} /></Field>
        <Field label="Industry"><input value={f.industry} onChange={set("industry")} maxLength={100} /></Field>
        <div className="grid2">
          <Field label="Segment">
            <select value={f.segment} onChange={set("segment")}>
              <option value="">—</option>
              {SEGMENTS.map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </select>
          </Field>
          <Field label="Employees"><input type="number" min={0} value={f.employee_count} onChange={set("employee_count")} /></Field>
          <Field label="Region"><input value={f.region} onChange={set("region")} maxLength={100} /></Field>
          <Field label="Country (2 letters)"><input value={f.country} onChange={set("country")} minLength={2} maxLength={2} /></Field>
        </div>
        <ErrorNote error={act.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={act.busy || f.name.trim() === ""}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
