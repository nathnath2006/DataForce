import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api";
import { companiesApi } from "../companies/api";
import { useWs } from "../context";
import { formatEur, formatDateTime, label, segmentLabel } from "../lib";
import { Confirm, Empty, ErrorNote, Loading, Modal, Tag, useAction, useLoad } from "../ui";
import { AccountForm } from "./Accounts";
import { ContactForm } from "./Contacts";
import { NoteThread } from "./Notes";
import { OrgChartPanel } from "../orgchart/OrgChartPanel";
import { MeetingsPanel } from "../meetings/MeetingsPanel";
import { DetailHeader, Summary3 } from "../shell/DetailHeader";
import { pickRoadmapDeal } from "../shell/logic";
import { useRegisterScope } from "../shell/scope";

export function AccountDetailPage() {
  const { id = "" } = useParams();
  const { ws } = useWs();
  const nav = useNavigate();
  const acc = useLoad(() => api.getAccount(ws.slug, id), [ws.slug, id]);
  const contacts = useLoad(() => api.listContacts(ws.slug, { account_id: id, limit: 1000 }), [ws.slug, id]);
  const chart = useLoad(() => api.getOrgChart(ws.slug, id), [ws.slug, id]);
  const deals = useLoad(() => api.listDeals(ws.slug, { account_id: id, limit: 1000 }), [ws.slug, id]);
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [picking, setPicking] = useState(false);
  const a = acc.data;
  useRegisterScope("account", a?.id, a?.name);
  const base = `/w/${ws.slug}`;
  const refreshAll = () => { acc.reload(); contacts.reload(); chart.reload(); };
  if (acc.loading && !a) return <Loading />;
  if (!a) return <ErrorNote error={acc.error} />;
  return (
    <section className="stack">
      <DetailHeader
        crumb={<><Link to={`${base}/accounts`}>Accounts</Link> / {a.name}</>}
        title={a.name}
        tags={<>
          {a.segment && <Tag>{segmentLabel(a.segment)}</Tag>}
          <Tag kind={a.n_open_deals > 0 ? "ok" : "mute"}>{a.n_open_deals} open deal(s)</Tag>
          <Tag kind="mute">{a.source}</Tag>
        </>}
        actions={<>
          <button onClick={() => setEditing(true)}>Edit</button>
          <button className="danger" onClick={() => setErasing(true)}>Erase account</button>
        </>}
        deal={deals.data ? pickRoadmapDeal(deals.data.items) : null}
      />
      <Summary3
        facts={<div className="card">
          <h2>Facts</h2>
          <dl className="facts">
            <dt>Company</dt>
            <dd>{a.company_id ? <Link to={`${base}/companies/${a.company_id}`}>{a.company_name ?? "Company"}</Link> : "—"}{" "}
              <button className="link" onClick={() => setPicking(true)}>{a.company_id ? "Change company" : "Set company"}</button></dd>
            <dt>Domain</dt><dd>{a.domain ?? "—"}</dd>
            <dt>Industry</dt><dd>{a.industry ?? "—"}</dd>
            <dt>Segment</dt><dd>{segmentLabel(a.segment)}</dd>
            <dt>Employees</dt><dd>{a.employee_count ?? "—"}</dd>
            <dt>Region</dt><dd>{a.region ?? "—"}{a.country ? ` (${a.country})` : ""}</dd>
            <dt>Source</dt><dd><Tag kind="mute">{a.source}</Tag></dd>
            <dt>Created</dt><dd>{formatDateTime(a.created_at)}</dd>
          </dl>
        </div>}
        middle={<>
          <MeetingsPanel scope={{ kind: "account", id: a.id }} />
        </>}
        insights={<>
          <div className="card">
            <h2>Comments</h2>
            <NoteThread kind="comment" parentId={a.id} />
          </div>
        </>}
      />

      <div className="card">
        <h2>Deals ({a.n_deals}, {a.n_open_deals} open)</h2>
        <ErrorNote error={deals.error} />
        {deals.data && deals.data.items.length === 0 ? <Empty>No deals.</Empty> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Deal</th><th>Stage</th><th className="num">Amount</th><th>Created</th></tr></thead>
            <tbody>{deals.data?.items.map((d) => (
              <tr key={d.id}><td>{d.name}</td><td><Tag>{label(d.stage)}</Tag></td><td className="num">{formatEur(d.amount_eur)}</td><td>{d.created_on}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <div className="row between"><h2>Contacts ({a.n_contacts})</h2><button onClick={() => setAdding(true)}>New contact</button></div>
        <ErrorNote error={contacts.error} />
        {contacts.data && contacts.data.items.length === 0 ? <Empty>No contacts.</Empty> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Name</th><th>Title</th><th>Reports to</th></tr></thead>
            <tbody>{contacts.data?.items.map((c) => (
              <tr key={c.id}><td><Link to={`${base}/contacts/${c.id}`}>{c.full_name}</Link></td><td>{c.title ?? "—"}</td><td>{c.reports_to_name ?? "—"}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <h2>Org chart</h2>
        <ErrorNote error={chart.error} />
        {chart.data && (
          <OrgChartPanel accountId={a.id} nodes={chart.data.nodes} base={base} onChanged={chart.reload} />
        )}
      </div>

      {picking && <CompanyPicker accountId={a.id} current={a.company_id ?? null} onClose={() => setPicking(false)} onSaved={refreshAll} />}
      {editing && <AccountForm account={a} onClose={() => setEditing(false)} onSaved={refreshAll} />}
      {adding && <ContactForm accountId={a.id} onClose={() => setAdding(false)} onSaved={refreshAll} />}
      {erasing && (
        <Confirm title="Erase account" confirmLabel="Erase permanently" danger typeToConfirm={a.name}
          onClose={() => setErasing(false)}
          onConfirm={async () => { await api.deleteAccount(ws.slug, a.id); nav(`${base}/accounts`); }}>
          <p>
            This is a GDPR erasure and cannot be undone. It also erases this account&apos;s {a.n_contacts} contact(s),
            their notes and stored emails and mobiles, the account&apos;s comments and its {a.n_deals} deal(s).
          </p>
        </Confirm>
      )}
    </section>
  );
}

function CompanyPicker(props: { accountId: string; current: string | null; onClose: () => void; onSaved: () => void }) {
  const { ws } = useWs();
  const list = useLoad(() => companiesApi.list(ws.slug, { limit: 200 }), [ws.slug]);
  const [sel, setSel] = useState(props.current ?? "");
  const act = useAction();
  return (
    <Modal title="Set company" onClose={props.onClose}>
      <div className="stack">
        <ErrorNote error={list.error} /><ErrorNote error={act.error} />
        <label>Company
          <select value={sel} onChange={(e) => setSel(e.target.value)}>
            <option value="">(none)</option>
            {list.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <div className="row end">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={act.busy} onClick={() => void act.run(async () => {
            await companiesApi.setAccountCompany(ws.slug, props.accountId, sel || null);
            props.onSaved(); props.onClose();
          })}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
