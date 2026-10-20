import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api";
import { companiesApi } from "../companies/api";
import { useWs } from "../context";
import { formatEur, formatDate, formatDateTime, label, segmentLabel } from "../lib";
import type { AccountOut } from "../types";
import { Confirm, Empty, ErrorNote, Loading, Modal, Tag, useAction, useLoad } from "../ui";
import { useAuth, useCanDelete } from "../auth";
import { AccountForm } from "./Accounts";
import { ContactForm } from "./Contacts";
import { NoteThread } from "./Notes";
import { OrgChartPanel } from "../orgchart/OrgChartPanel";
import { MeetingsPanel } from "../meetings/MeetingsPanel";
import { ProcessBar, RecordPage, SummaryLayout, type RecordAction } from "../record/RecordPage";
import { ICONS, NewDealDialog, ico } from "../record/bits";
import { pickRoadmapDeal } from "../shell/logic";
import { useRegisterScope } from "../shell/scope";
import { Timeline } from "../activity/Timeline";
import { activityApi } from "../activity/api";
import { DealAiPanel } from "../genai";

export function AccountDetailPage() {
  const { id = "" } = useParams();
  const { ws, users } = useWs();
  const nav = useNavigate();
  const mayDelete = useCanDelete();
  const { isAdmin } = useAuth();
  const acc = useLoad(() => api.getAccount(ws.slug, id), [ws.slug, id]);
  const contacts = useLoad(() => api.listContacts(ws.slug, { account_id: id, limit: 1000 }), [ws.slug, id]);
  const chart = useLoad(() => api.getOrgChart(ws.slug, id), [ws.slug, id]);
  const deals = useLoad(() => api.listDeals(ws.slug, { account_id: id, limit: 1000 }), [ws.slug, id]);
  const last = useLoad(() => activityApi.timeline(ws.slug, "accounts", id, { limit: 1 }), [ws.slug, id]);
  const a0 = acc.data as (AccountOut & { owner_id?: string | null; owner_name?: string | null }) | null;
  const company = useLoad(
    () => (a0?.company_id ? companiesApi.get(ws.slug, a0.company_id) : Promise.resolve(null)),
    [ws.slug, a0?.company_id]);
  const [tab, setTab] = useState("summary");
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addingDeal, setAddingDeal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [picking, setPicking] = useState(false);
  const a = a0;
  useRegisterScope("account", a?.id, a?.name);
  const base = `/w/${ws.slug}`;
  const refreshAll = () => { acc.reload(); contacts.reload(); chart.reload(); deals.reload(); last.reload(); };
  if (acc.loading && !a) return <Loading />;
  if (!a) return <ErrorNote error={acc.error} />;
  const dealItems = deals.data?.items ?? [];
  const pipeline = dealItems.filter((d) => !d.is_closed).reduce((s, d) => s + Number(d.amount_eur ?? 0), 0);
  const roadmap = deals.data ? pickRoadmapDeal(deals.data.items) : null;
  const ownerId = a.owner_id ?? roadmap?.owner_id ?? dealItems.find((d) => d.owner_id)?.owner_id ?? null;
  const ownerName = a.owner_name ?? users.find((u) => u.id === ownerId)?.display_name ?? roadmap?.owner_name ?? "—";
  const lastAt = last.data?.items[0]?.at;
  const canDelete = mayDelete(ownerId);
  const actions: RecordAction[] = [
    { key: "edit", label: "Edit", icon: ico(ICONS.edit), onClick: () => setEditing(true) },
    { key: "deal", label: "New deal", icon: ico(ICONS.plus), onClick: () => setAddingDeal(true) },
    { key: "contact", label: "New contact", icon: ico(ICONS.plus), onClick: () => setAdding(true) },
    ...(canDelete ? [{ key: "delete", label: "Delete", kind: "danger" as const, icon: ico(ICONS.trash), onClick: () => setDeleting(true) }] : []),
    ...(isAdmin ? [{ key: "erase", label: "Erase (GDPR)", kind: "danger" as const, icon: ico(ICONS.erase), onClick: () => setErasing(true) }] : []),
  ];
  const facts = (
    <div className="card">
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
    </div>
  );
  const dealsCard = (
    <div className="card">
      <h2>Deals ({a.n_deals}, {a.n_open_deals} open)</h2>
      <ErrorNote error={deals.error} />
      {deals.data && dealItems.length === 0 ? <Empty>No deals.</Empty> : (
        <div className="tablewrap"><table>
          <thead><tr><th>Deal</th><th>Stage</th><th className="num">Amount</th></tr></thead>
          <tbody>{dealItems.map((d) => (
            <tr key={d.id}><td><Link to={`${base}/deals/${d.id}`}>{d.name}</Link></td><td><Tag>{label(d.stage)}</Tag></td><td className="num">{formatEur(d.amount_eur)}</td></tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
  const peopleCard = (
    <div className="card">
      <div className="row between"><h2>People ({a.n_contacts})</h2><button onClick={() => setAdding(true)}>New contact</button></div>
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
  );
  const siblings = company.data?.accounts.filter((x) => x.id !== a.id) ?? [];
  return (
    <>
      <RecordPage
        crumb={<><Link to={`${base}/accounts`}>Accounts</Link> / {a.name}</>}
        title={a.name}
        tags={<>
          {a.segment && <Tag>{segmentLabel(a.segment)}</Tag>}
          <Tag kind={a.n_open_deals > 0 ? "ok" : "mute"}>{a.n_open_deals} open deal(s)</Tag>
          <Tag kind="mute">{a.source}</Tag>
        </>}
        actions={actions}
        fields={[
          { label: "Segment", value: segmentLabel(a.segment) },
          { label: "Industry", value: a.industry ?? "—" },
          { label: "Open pipeline", value: formatEur(pipeline) },
          { label: "Last activity", value: lastAt ? formatDate(lastAt) : "—" },
        ]}
        owner={{ label: "Owner", value: ownerName }}
        process={roadmap ? <ProcessBar stage={roadmap.stage} name={roadmap.name} /> : undefined}
        tab={tab} onTab={setTab}
        tabs={[
          { key: "summary", label: "Summary", content: (
            <SummaryLayout main={<>{facts}{dealsCard}{peopleCard}
              <div className="card"><h2>Comments</h2><NoteThread kind="comment" parentId={a.id} /></div></>}
              side={<>
                <div className="card stack"><h2>Timeline</h2><Timeline scope="accounts" id={a.id} /></div>
                <div className="card stack"><h2>AI assistance</h2><DealAiPanel ws={ws.slug} accountId={a.id} /></div>
              </>} />
          ) },
          { key: "org", label: "Org chart", content: (
            <div className="card">
              <h2>Org chart</h2>
              <ErrorNote error={chart.error} />
              {chart.data && <OrgChartPanel accountId={a.id} nodes={chart.data.nodes} base={base} onChanged={chart.reload} />}
            </div>
          ) },
          { key: "meetings", label: "Meetings", content: <MeetingsPanel scope={{ kind: "account", id: a.id }} /> },
          { key: "related", label: "Related", content: (
            <div className="stack">
              <div className="card"><h2>Company</h2>
                {a.company_id ? <p><Link to={`${base}/companies/${a.company_id}`}>{a.company_name ?? "Company"}</Link></p> : <Empty>Not linked to a company.</Empty>}
              </div>
              <div className="card"><h2>Sibling accounts ({siblings.length})</h2>
                <ErrorNote error={company.error} />
                {siblings.length === 0 ? <Empty>No other account in this company.</Empty> : (
                  <ul className="plain">{siblings.map((x) => <li key={x.id}><Link to={`${base}/accounts/${x.id}`}>{x.name}</Link></li>)}</ul>
                )}
              </div>
            </div>
          ) },
        ]}
      />
      {picking && <CompanyPicker accountId={a.id} current={a.company_id ?? null} onClose={() => setPicking(false)} onSaved={refreshAll} />}
      {editing && <AccountForm account={a} onClose={() => setEditing(false)} onSaved={refreshAll} />}
      {adding && <ContactForm accountId={a.id} onClose={() => setAdding(false)} onSaved={refreshAll} />}
      {addingDeal && <NewDealDialog accountId={a.id} accountName={a.name} onClose={() => setAddingDeal(false)} onSaved={refreshAll} />}
      {deleting && (
        <Confirm title="Delete account" confirmLabel="Delete" danger onClose={() => setDeleting(false)}
          onConfirm={async () => { await api.deleteAccount(ws.slug, a.id); nav(`${base}/accounts`); }}>
          <p>This deletes the account with its {a.n_contacts} contact(s) and {a.n_deals} deal(s). It cannot be undone.</p>
        </Confirm>
      )}
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
    </>
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
