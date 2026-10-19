import { useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { formatEur, label } from "../lib";
import { Empty, ErrorNote, Loading, Tag, useLoad } from "../ui";
import { DetailHeader, Summary3 } from "../shell/DetailHeader";
import { useRegisterScope } from "../shell/scope";
import { meetingsApi } from "../meetings/api";
import { DeleteMeeting, MeetingTable, TranscriptDialog } from "../meetings/MeetingsPanel";
import type { DocumentOut } from "../meetings/types";
import { DealForm } from "./Deals";

export function DealDetailPage() {
  const { id = "" } = useParams();
  const { ws } = useWs();
  const base = `/w/${ws.slug}`;
  const deal = useLoad(() => api.getDeal(ws.slug, id), [ws.slug, id]);
  const d = deal.data;
  const people = useLoad(
    () => (d ? api.listContacts(ws.slug, { account_id: d.account_id, limit: 1000 }) : Promise.resolve(null)),
    [ws.slug, d?.account_id]);
  const meetings = useLoad(
    () => (d ? meetingsApi.forAccount(ws.slug, d.account_id) : Promise.resolve(null)),
    [ws.slug, d?.account_id]);
  const [editing, setEditing] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  useRegisterScope("deal", d?.id, d?.name);
  if (deal.loading && !d) return <Loading />;
  if (!d) return <ErrorNote error={deal.error} />;
  const mine = meetings.data?.filter((m) => m.deal_id === d.id) ?? [];
  return (
    <section className="stack">
      <DetailHeader
        crumb={<><Link to={`${base}/deals`}>Deals</Link> / {d.name}</>}
        title={d.name}
        tags={<>
          <Tag>{label(d.stage)}</Tag>
          <Tag kind="mute">{d.source}</Tag>
        </>}
        actions={<button onClick={() => setEditing(true)}>Edit</button>}
        deal={d}
      />
      <Summary3
        facts={<div className="card">
          <h2>Facts</h2>
          <dl className="facts">
            <dt>Account</dt><dd><Link to={`${base}/accounts/${d.account_id}`}>{d.account_name}</Link></dd>
            <dt>Amount</dt><dd>{formatEur(d.amount_eur)}</dd>
            <dt>Stage</dt><dd>{label(d.stage)}</dd>
            <dt>Created</dt><dd>{d.created_on}</dd>
            <dt>Closed</dt><dd>{d.closed_on ?? "—"}</dd>
            <dt>Owner</dt><dd>{d.owner_name ?? "—"}</dd>
            <dt>Lead source</dt><dd>{d.lead_source ? label(d.lead_source) : "—"}</dd>
            <dt>Lost reason</dt><dd>{d.lost_reason ?? "—"}</dd>
          </dl>
        </div>}
        middle={<div className="card stack">
          <h2>Meetings</h2>
          <ErrorNote error={meetings.error} />
          {meetings.data && mine.length === 0 && <Empty>No meeting tied to this deal.</Empty>}
          {mine.length > 0 && <MeetingTable docs={mine} showAccount={false} onView={setViewing} onDelete={setDeleting} />}
        </div>}
        insights={<div className="card">
          <h2>People</h2>
          <ErrorNote error={people.error} />
          {people.data && people.data.items.length === 0 ? <Empty>No contacts on this account.</Empty> : (
            <div className="tablewrap"><table>
              <thead><tr><th>Name</th><th>Title</th><th>Reports to</th></tr></thead>
              <tbody>{people.data?.items.map((c) => (
                <tr key={c.id}><td><Link to={`${base}/contacts/${c.id}`}>{c.full_name}</Link></td><td>{c.title ?? "—"}</td><td>{c.reports_to_name ?? "—"}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>}
      />
      {editing && <DealForm deal={d} onClose={() => setEditing(false)} onSaved={deal.reload} />}
      {viewing && <TranscriptDialog id={viewing} onClose={() => setViewing(null)} />}
      {deleting && <DeleteMeeting doc={deleting} onClose={() => setDeleting(null)} onDone={meetings.reload} />}
    </section>
  );
}
