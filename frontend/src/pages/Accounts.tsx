import { useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { segmentLabel } from "../lib";
import { SEGMENTS, type AccountCreate, type AccountOut, type Segment } from "../types";
import { DataQualityCard } from "../quality/DataQuality";
import { ErrorNote, Field, Modal, Tag, emptyToNull, useAction } from "../ui";
import { DataTable, type Column } from "../table/DataTable";
import { Pager } from "../table/Pager";
import { useListQuery, useUrlSearch } from "../table/useListQuery";

const ACCOUNT_COLUMNS: Column<AccountOut>[] = [
  { key: "name", header: "Name", sortable: true, cell: (a) => <>{a.name}{a.domain && <div className="muted small">{a.domain}</div>}</> },
  { key: "industry", header: "Industry", sortable: true, cell: (a) => a.industry ?? "—" },
  { key: "segment", header: "Segment", sortable: true, cell: (a) => (a.segment ? <Tag>{segmentLabel(a.segment)}</Tag> : "—") },
  { key: "region", header: "Region", sortable: true, cell: (a) => a.region ?? "—" },
  { key: "n_contacts", header: "Contacts", numeric: true, cell: (a) => a.n_contacts },
  { key: "n_open_deals", header: "Open deals", numeric: true, cell: (a) => a.n_open_deals },
];

export function AccountsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const [creating, setCreating] = useState(false);
  const list = useListQuery<AccountOut>({
    resource: "accounts", filters: ["q", "segment"], defaultSort: { key: "name", dir: "asc" },
    fetch: (p, signal) => api.listAccounts(ws.slug, p, signal),
  });
  const [text, setText] = useUrlSearch(list.f("q"), (v) => list.setFilter("q", v, true));
  const { data } = list;
  return (
    <section>
      <div className="row between wrap">
        <h1>Accounts</h1>
        <button className="primary" onClick={() => setCreating(true)}>New account</button>
      </div>
      <DataQualityCard />
      <div className="row wrap filters">
        <input type="search" placeholder="Search name or domain" aria-label="Search" value={text} onChange={(e) => setText(e.target.value)} />
        <select aria-label="Segment" value={list.f("segment")} onChange={(e) => list.setFilter("segment", e.target.value)}>
          <option value="">All segments</option>
          {SEGMENTS.map((s) => <option key={s} value={s}>{segmentLabel(s)}</option>)}
        </select>
      </div>
      <ErrorNote error={list.error} />
      <DataTable columns={ACCOUNT_COLUMNS} rows={data?.items ?? []} rowKey={(a) => a.id} rowHref={(a) => a.id}
        sort={list.sort} onSort={list.setSort} loading={list.loading} caption="Accounts" empty="No accounts match." />
      {data && <Pager offset={data.offset} limit={data.limit} shown={data.items.length} total={data.total} onOffset={list.setOffset} />}
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
              {SEGMENTS.map((s) => <option key={s} value={s}>{segmentLabel(s)}</option>)}
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
