import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api";
import { AskPanel } from "../assistant/AskPanel";
import { useWs } from "../context";
import { formatDate, formatDateTime, formatEur, label } from "../lib";
import type { AccountOut } from "../types";
import { Confirm, Empty, ErrorNote, Loading, Modal, Tag, useAction, useDebounced, useLoad } from "../ui";
import { companiesApi } from "./api";
import { CompanyForm, InteractedBadge } from "./CompaniesPage";
import { formatAddress, formatSiren, sizeLabel } from "./format";

export function CompanyDetailPage() {
  const { id = "" } = useParams();
  const { ws } = useWs();
  const nav = useNavigate();
  const base = `/w/${ws.slug}`;
  const d = useLoad(() => companiesApi.get(ws.slug, id), [ws.slug, id]);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [linking, setLinking] = useState(false);
  const act = useAction();
  const v = d.data;
  if (d.loading && !v) return <Loading />;
  if (!v) return <ErrorNote error={d.error} />;
  const c = v.company;
  const open = c.n_open_deals;
  const won = v.deals.filter((x) => x.stage === "closed_won").length;
  const lost = v.deals.filter((x) => x.stage === "closed_lost").length;

  return (
    <section className="stack">
      <p className="crumb"><Link to={`${base}/companies`}>Companies</Link> / {c.name}</p>
      <div className="row between wrap">
        <h1>{c.name}</h1>
        <div className="row wrap">
          <button disabled={!c.siren || act.busy} title={c.siren ? "" : "Needs a SIREN"}
            onClick={() => void act.run(async () => { await companiesApi.refresh(ws.slug, c.id); d.reload(); })}>
            Refresh from registry
          </button>
          <button onClick={() => setEditing(true)}>Edit</button>
          <button className="danger" onClick={() => setDeleting(true)}>Delete</button>
        </div>
      </div>
      <ErrorNote error={act.error} />
      <div className="row wrap"><InteractedBadge c={c} />
        <span className="muted small">Last interaction: {c.last_interaction ? formatDate(c.last_interaction) : "none"}</span></div>
      <dl className="facts">
        <dt>SIREN</dt><dd>{formatSiren(c.siren)}</dd>
        <dt>Address</dt><dd>{formatAddress(c)}</dd>
        <dt>Domain</dt><dd>{c.domain ?? "—"}</dd>
        <dt>Activity code</dt><dd>{c.naf_code ?? "—"}</dd>
        <dt>Size</dt><dd>{sizeLabel(c.size_bracket)}</dd>
        <dt>Category</dt><dd>{c.category ?? "—"}</dd>
        <dt>Source</dt><dd><Tag kind="mute">{c.source}</Tag></dd>
      </dl>

      <div className="kpis" aria-label="Key figures (exact counts)">
        <div className="kpi"><b>{c.n_accounts}</b><span>accounts · exact count</span></div>
        <div className="kpi"><b>{c.n_contacts}</b><span>contacts · exact count</span></div>
        <div className="kpi"><b>{c.n_deals}</b><span>deals · {open} open · {won} won · {lost} lost</span></div>
        <div className="kpi"><b>{formatEur(c.won_amount_eur)}</b><span>won amount · exact sum</span></div>
      </div>

      <div className="card">
        <div className="row between"><h2>Accounts ({v.accounts.length})</h2><button onClick={() => setLinking(true)}>Link an account</button></div>
        {v.accounts.length === 0 ? <Empty>No linked accounts.</Empty> : (
          <ul className="plain">{v.accounts.map((a) => (
            <li key={a.id} className="row between">
              <Link to={`${base}/accounts/${a.id}`}>{a.name}</Link>
              <button className="link" onClick={() => void act.run(async () => { await companiesApi.setAccountCompany(ws.slug, a.id, null); d.reload(); })}>Unlink</button>
            </li>
          ))}</ul>
        )}
      </div>

      <div className="card">
        <h2>Contacts ({v.contacts.length})</h2>
        {v.contacts.length === 0 ? <Empty>No contacts.</Empty> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Name</th><th>Title</th><th>Account</th></tr></thead>
            <tbody>{v.contacts.map((x) => (
              <tr key={x.id}><td><Link to={`${base}/contacts/${x.id}`}>{x.full_name}</Link></td><td>{x.title ?? "—"}</td><td>{x.account_name}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <h2>Deals ({v.deals.length})</h2>
        {v.deals.length === 0 ? <Empty>No deals.</Empty> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Deal</th><th>Account</th><th>Stage</th><th className="num">Amount</th><th>Created</th></tr></thead>
            <tbody>{v.deals.map((x) => (
              <tr key={x.id}><td>{x.name}</td><td>{x.account_name}</td><td><Tag>{label(x.stage)}</Tag></td>
                <td className="num">{formatEur(x.amount_eur)}</td><td>{x.created_on}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <h2>Activity</h2>
        {v.activity.length === 0 ? <Empty>No activity yet.</Empty> : (
          <ul className="timeline">{v.activity.map((x, i) => (
            <li key={i}>
              <div className="meta">{x.kind.startsWith("deal_") ? formatDate(x.at) : formatDateTime(x.at)} · {label(x.kind)}</div>
              <strong>{x.title}</strong>
              {x.excerpt && <p className="pre">{x.excerpt}</p>}
            </li>
          ))}</ul>
        )}
      </div>

      <AskPanel scope={{ kind: "company", id: c.id }} />

      {editing && <CompanyForm company={c} onClose={() => setEditing(false)} onSaved={() => d.reload()} />}
      {deleting && (
        <Confirm title="Delete company" confirmLabel="Delete" danger onClose={() => setDeleting(false)}
          onConfirm={async () => { await companiesApi.remove(ws.slug, c.id); nav(`${base}/companies`); }}>
          <p>The company is deleted. Its accounts stay in the CRM and are unlinked.</p>
        </Confirm>
      )}
      {linking && <AccountPicker onClose={() => setLinking(false)}
        onPick={async (a: AccountOut) => { await companiesApi.setAccountCompany(ws.slug, a.id, c.id); d.reload(); }} />}
    </section>
  );
}

function AccountPicker(props: { onClose: () => void; onPick: (a: AccountOut) => Promise<void> }) {
  const { ws } = useWs();
  const [text, setText] = useState("");
  const dq = useDebounced(text.trim());
  const r = useLoad(() => api.listAccounts(ws.slug, { q: dq, limit: 20 }), [ws.slug, dq]);
  const a = useAction();
  return (
    <Modal title="Link an account" onClose={props.onClose}>
      <div className="stack">
        <input type="search" aria-label="Search accounts" placeholder="Account name" value={text} onChange={(e) => setText(e.target.value)} />
        <ErrorNote error={r.error} /><ErrorNote error={a.error} />
        <ul className="plain">{r.data?.items.map((x) => (
          <li key={x.id} className="row between">
            <span>{x.name} {x.company_name && <span className="muted small">(now in {x.company_name})</span>}</span>
            <button disabled={a.busy} onClick={() => void a.run(async () => { await props.onPick(x); props.onClose(); })}>Link</button>
          </li>
        ))}</ul>
      </div>
    </Modal>
  );
}
