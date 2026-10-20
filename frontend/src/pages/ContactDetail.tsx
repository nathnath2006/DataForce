import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import type { ChannelKind, ContactOut } from "../types";
import { Confirm, Empty, ErrorNote, Loading, Modal, Tag, useAction, useLoad } from "../ui";
import { useAuth, useCanDelete } from "../auth";
import { ContactForm } from "./Contacts";
import { NoteThread } from "./Notes";
import { TitleClassRow } from "../titles/TitleClass";
import { RecordPage, SummaryLayout, type RecordAction } from "../record/RecordPage";
import { ICONS, ico } from "../record/bits";
import { pickRoadmapDeal } from "../shell/logic";
import { Timeline } from "../activity/Timeline";
import { ActivityPanel } from "../activity/ActivityPanel";
import { OrgChartPanel } from "../orgchart/OrgChartPanel";
import { classLabel } from "../orgchart/model";

export function ContactDetailPage() {
  const { id = "" } = useParams();
  const { ws, users } = useWs();
  const nav = useNavigate();
  const mayDelete = useCanDelete();
  const { isAdmin } = useAuth();
  const base = `/w/${ws.slug}`;
  const c = useLoad(() => api.getContact(ws.slug, id), [ws.slug, id]);
  const acct = c.data?.account_id;
  const sameAcct = useLoad(
    () => (acct ? api.listContacts(ws.slug, { account_id: acct, limit: 1000 }) : Promise.resolve(null)), [ws.slug, acct]);
  const deals = useLoad(
    () => (acct ? api.listDeals(ws.slug, { account_id: acct, limit: 1000 }) : Promise.resolve(null)), [ws.slug, acct]);
  const chart = useLoad(() => (acct ? api.getOrgChart(ws.slug, acct) : Promise.resolve(null)), [ws.slug, acct]);
  const [tab, setTab] = useState("summary");
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [logging, setLogging] = useState(false);
  const [tick, setTick] = useState(0);
  const rep = useAction();
  const k = c.data;
  const people = sameAcct.data?.items ?? [];
  const only = useMemo(() => {
    const ids = new Set<string>();
    if (!k) return ids;
    const by = new Map(people.map((p) => [p.id, p]));
    ids.add(k.id);
    for (let cur = k.reports_to_id, i = 0; cur && !ids.has(cur) && i < 50; i++) { ids.add(cur); cur = by.get(cur)?.reports_to_id ?? null; }
    for (const p of people) if (p.reports_to_id === k.id) ids.add(p.id);
    return ids;
  }, [k, people]);
  if (c.loading && !k) return <Loading />;
  if (!k) return <ErrorNote error={c.error} />;
  const reports = people.filter((p) => p.reports_to_id === k.id);
  const dealItems = deals.data?.items ?? [];
  const roadmap = pickRoadmapDeal(dealItems);
  const ownerId = roadmap?.owner_id ?? dealItems.find((d) => d.owner_id)?.owner_id ?? null;
  const ownerName = roadmap?.owner_name ?? users.find((u) => u.id === ownerId)?.display_name ?? "—";
  const actions: RecordAction[] = [
    { key: "edit", label: "Edit", icon: ico(ICONS.edit), onClick: () => setEditing(true) },
    ...(roadmap ? [{ key: "log", label: "Log activity", icon: ico(ICONS.plus), onClick: () => setLogging(true) }] : []),
    ...(mayDelete(ownerId) ? [{ key: "delete", label: "Delete", kind: "danger" as const, icon: ico(ICONS.trash), onClick: () => setDeleting(true) }] : []),
    ...(isAdmin ? [{ key: "erase", label: "Erase (GDPR)", kind: "danger" as const, icon: ico(ICONS.erase), onClick: () => setErasing(true) }] : []),
  ];
  const facts = (
    <div className="card"><h2>Facts</h2><dl className="facts">
      <dt>Title</dt><dd>{k.title ?? "—"}</dd>
      <TitleClassRow contactId={k.id} fn={k.title_function} sen={k.title_seniority} source={k.title_source} flag={k.title_flag} onChanged={c.reload} />
      <dt>Account</dt><dd><Link to={`${base}/accounts/${k.account_id}`}>{k.account_name}</Link></dd>
      <dt>Reports to</dt>
      <dd>
        <select aria-label="Reports to" value={k.reports_to_id ?? ""} disabled={rep.busy}
          onChange={(e) => void rep.run(async () => { await api.setReportsTo(ws.slug, k.id, e.target.value || null); c.reload(); sameAcct.reload(); chart.reload(); })}>
          <option value="">(nobody)</option>
          {people.filter((p) => p.id !== k.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
        </select>
        <ErrorNote error={rep.error} />
      </dd>
      <dt>Direct reports</dt>
      <dd>{reports.length === 0 ? "—" : reports.map((r, i) => (
        <span key={r.id}>{i > 0 && ", "}<Link to={`${base}/contacts/${r.id}`}>{r.full_name}</Link></span>
      ))}</dd>
      <dt>Source</dt><dd><Tag kind="mute">{k.source}</Tag></dd>
    </dl></div>
  );
  return (
    <>
      <RecordPage
        crumb={<><Link to={`${base}/contacts`}>Contacts</Link> / {k.full_name}</>}
        title={k.full_name}
        tags={<>{k.title && <Tag>{k.title}</Tag>}<Tag kind="mute">{k.source}</Tag></>}
        actions={actions}
        fields={[
          { label: "Title", value: k.title ?? "—" },
          { label: "Function · seniority", value: classLabel(k.title_function, k.title_seniority) },
          { label: "Account", value: <Link to={`${base}/accounts/${k.account_id}`}>{k.account_name}</Link> },
          { label: "Reports to", value: k.reports_to_id ? <Link to={`${base}/contacts/${k.reports_to_id}`}>{k.reports_to_name}</Link> : "—" },
        ]}
        owner={{ label: "Owner (via account)", value: ownerName }}
        tab={tab} onTab={setTab}
        tabs={[
          { key: "summary", label: "Summary", content: (
            <SummaryLayout main={<>{facts}
              <div className="card"><h2>Notes</h2><p className="muted">{k.n_notes} note(s). <button className="link" onClick={() => setTab("notes")}>Open notes</button></p></div></>}
              side={<>
                <div className="card stack"><h2>Account timeline</h2><p className="muted small">Shows the activity of {k.account_name}; per-contact filtering is not available.</p>
                  <Timeline scope="accounts" id={k.account_id} refreshKey={tick} /></div>
                <EnrichPanel contact={k} onChanged={c.reload} />
              </>} />
          ) },
          { key: "org", label: "Org chart position", content: (
            <div className="card stack">
              <h2>Position in {k.account_name}</h2>
              <p className="muted small">Manager chain above, direct reports below. Click a person to open them.</p>
              <ErrorNote error={chart.error} />
              {chart.data && <OrgChartPanel accountId={k.account_id} nodes={chart.data.nodes} base={base} current={k.id} only={only}
                onChanged={() => { chart.reload(); c.reload(); sameAcct.reload(); }} />}
            </div>
          ) },
          { key: "notes", label: "Notes", content: <div className="card"><h2>Notes</h2><NoteThread kind="note" parentId={k.id} /></div> },
        ]}
      />
      {editing && <ContactForm contact={k} onClose={() => setEditing(false)} onSaved={() => c.reload()} />}
      {logging && roadmap && (
        <Modal title={`Log activity on ${roadmap.name}`} onClose={() => setLogging(false)}>
          <ActivityPanel deal={roadmap} contacts={people} onLogged={() => { setTick((n) => n + 1); setLogging(false); }} />
        </Modal>
      )}
      {deleting && (
        <Confirm title="Delete contact" confirmLabel="Delete" danger onClose={() => setDeleting(false)}
          onConfirm={async () => { await api.deleteContact(ws.slug, k.id); nav(`${base}/accounts/${k.account_id}`); }}>
          <p>The contact and its {k.n_notes} note(s) are deleted. This cannot be undone.</p>
        </Confirm>
      )}
      {erasing && (
        <Confirm title="Erase contact" confirmLabel="Erase permanently" danger onClose={() => setErasing(false)}
          onConfirm={async () => { await api.deleteContact(ws.slug, k.id); nav(`${base}/accounts/${k.account_id}`); }}>
          <p>This cannot be undone. The contact, its {k.n_notes} note(s) and its stored emails and mobiles are erased.</p>
        </Confirm>
      )}
    </>
  );
}

function EnrichPanel({ contact, onChanged }: { contact: ContactOut; onChanged: () => void }) {
  const { ws } = useWs();
  const conn = useLoad(() => api.getConnector(ws.slug), [ws.slug]);
  const channels = useLoad(() => api.listChannels(ws.slug, contact.id), [ws.slug, contact.id]);
  const [want, setWant] = useState<Record<ChannelKind, boolean>>({ email: true, mobile: false });
  const [confirming, setConfirming] = useState(false);
  const [msg, setMsg] = useState<string[]>([]);
  const [delCh, setDelCh] = useState<string | null>(null);
  const act = useAction();
  const p = conn.data?.pricing;
  const mode = conn.data?.enrichment_mode;
  const kinds = (["email", "mobile"] as ChannelKind[]).filter((x) => want[x]);
  const estimate = mode === "tamtam" && p ? kinds.reduce((s, x) => s + p[x], 0) : 0;
  const paid = estimate > 0;

  const run = () => act.run(async () => {
    const r = await api.enrich(ws.slug, contact.id, { want: kinds, confirm_paid: paid, max_credits: estimate });
    setMsg([
      `Lookup done (${r.mode}): ${r.channels.length} value(s) stored, ${r.credits_used} credit(s) used.`,
      ...(r.anomalous ? ["The provider's answer looked anomalous."] : []), ...r.notes,
    ]);
    channels.reload();
    onChanged();
  });

  return (
    <div className="card">
      <h2>Enrich</h2>
      <ErrorNote error={conn.error} />
      {mode === "fake" && <p><Tag kind="warn">fake</Tag> Results come from a fake provider (synthetic data). No credits are spent.</p>}
      {mode === "tamtam" && <p><Tag kind="ok">TamTam</Tag> Real lookups; credits are spent.</p>}
      {mode === "off" && <p className="muted">Enrichment is off. Connect TamTam under <Link to={`/w/${ws.slug}/settings`}>Settings</Link>.</p>}
      {conn.data && mode !== "off" && (
        <>
          <div className="row wrap">
            {(["email", "mobile"] as ChannelKind[]).map((x) => (
              <label key={x} className="check">
                <input type="checkbox" checked={want[x]} onChange={(e) => setWant({ ...want, [x]: e.target.checked })} />
                {x === "email" ? "Email" : "Mobile"}{mode === "tamtam" && p ? ` (${p[x]} credits${p.assumed ? ", assumed" : ""})` : ""}
              </label>
            ))}
          </div>
          <p className="muted small">
            {mode === "tamtam" ? `Estimated cost: ${estimate} credits (ceiling per call ${p?.ceiling}).` : "Estimated cost: 0 credits."}
          </p>
          <button className="primary" disabled={kinds.length === 0 || act.busy}
            onClick={() => (paid ? setConfirming(true) : void run())}>
            {paid ? `Enrich (${estimate} credits)…` : "Enrich"}
          </button>
        </>
      )}
      <ErrorNote error={act.error} />
      {msg.length > 0 && <ul className="plain">{msg.map((m, i) => <li key={i}>{m}</li>)}</ul>}

      <h3>Stored channels</h3>
      <ErrorNote error={channels.error} />
      {channels.data && channels.data.length === 0 ? <Empty>None stored.</Empty> : (
        <ul className="plain">
          {channels.data?.map((ch) => (
            <li key={ch.id} className="row between">
              <span><Tag>{ch.kind}</Tag> <span className="pre">{ch.value}</span>
                <span className="muted small"> · {ch.provider} · {ch.credits_used} cr · {formatDateTime(ch.fetched_at)}</span></span>
              <button className="link" onClick={() => setDelCh(ch.id)}>Delete</button>
            </li>
          ))}
        </ul>
      )}
      {confirming && (
        <Confirm title="Spend credits?" confirmLabel={`Spend ${estimate} credits`} onClose={() => setConfirming(false)} onConfirm={run}>
          <p>This lookup will use up to <strong>{estimate} credits</strong> of your TamTam account ({kinds.join(" + ")} for {contact.full_name}).</p>
          <p className="muted small">The server refuses if the price has risen above this estimate.</p>
        </Confirm>
      )}
      {delCh && (
        <Confirm title="Delete stored value" confirmLabel="Delete" danger onClose={() => setDelCh(null)}
          onConfirm={async () => { await api.deleteChannel(ws.slug, contact.id, delCh); channels.reload(); onChanged(); }}>
          <p>The stored value is erased. Looking it up again would cost credits.</p>
        </Confirm>
      )}
    </div>
  );
}
