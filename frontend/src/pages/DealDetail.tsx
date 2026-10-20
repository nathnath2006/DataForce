import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { formatEur, label } from "../lib";
import { Empty, ErrorNote, Loading, Tag, todayIso, useAction, useLoad } from "../ui";
import { useCanDelete } from "../auth";
import { ProcessBar, RecordPage, SummaryLayout, type RecordAction } from "../record/RecordPage";
import { useRegisterScope } from "../shell/scope";
import { meetingsApi } from "../meetings/api";
import { DeleteMeeting, MeetingTable, TranscriptDialog } from "../meetings/MeetingsPanel";
import type { DocumentOut } from "../meetings/types";
import { DealForm } from "./Deals";
import { ActivityPanel } from "../activity/ActivityPanel";
import { activityApi } from "../activity/api";
import { StageControl } from "../activity/StageControl";
import { TaskList } from "../activity/TaskList";
import { Timeline } from "../activity/Timeline";
import { DealAiPanel } from "../genai";
import { DealEmailsPanel } from "../mailbox";

export function DealDetailPage() {
  const { id = "" } = useParams();
  const { ws } = useWs();
  const mayDelete = useCanDelete();
  const [tab, setTab] = useState("summary");
  const close = useAction();
  const base = `/w/${ws.slug}`;
  const deal = useLoad(() => api.getDeal(ws.slug, id), [ws.slug, id]);
  const canDelete = mayDelete(deal.data?.owner_id);
  const d = deal.data;
  const people = useLoad(
    () => (d ? api.listContacts(ws.slug, { account_id: d.account_id, limit: 1000 }) : Promise.resolve(null)),
    [ws.slug, d?.account_id]);
  const meetings = useLoad(
    () => (d ? meetingsApi.forAccount(ws.slug, d.account_id) : Promise.resolve(null)),
    [ws.slug, d?.account_id]);
  const [editing, setEditing] = useState(false);
  const [tick, setTick] = useState(0);
  const [viewing, setViewing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  useRegisterScope("deal", d?.id, d?.name);
  const nav = useNavigate();
  if (deal.loading && !d) return <Loading />;
  if (!d) return <ErrorNote error={deal.error} />;
  const mine = meetings.data?.filter((m) => m.deal_id === d.id) ?? [];
  const moveTo = async (stage: "closed_won" | "closed_lost") => {
    const r = await close.run(() => activityApi.moveStage(ws.slug, d.id, {
      stage, changed_on: todayIso(), lost_reason: null,
    }));
    if (r) { deal.reload(); setTick((n) => n + 1); }
  };
  const ico = (path: string) => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>
  );
  const actions: RecordAction[] = [
    { key: "edit", label: "Edit", icon: ico("M4 20h4L19 9l-4-4L4 16z"), onClick: () => setEditing(true) },
    { key: "activity", label: "New activity", icon: ico("M12 5v14M5 12h14"), onClick: () => {
      setTab("activity");
      setTimeout(() => document.getElementById("deal-activity")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } },
    { key: "refresh", label: "Refresh", icon: ico("M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"), onClick: () => { deal.reload(); setTick((n) => n + 1); } },
    ...(d.is_closed ? [] : [
      { key: "won", label: "Close as won", icon: ico("M5 12l5 5 9-10"), disabled: close.busy, onClick: () => void moveTo("closed_won") },
      { key: "lost", label: "Close as lost", icon: ico("M6 6l12 12M18 6L6 18"), disabled: close.busy, onClick: () => void moveTo("closed_lost") },
    ]),
    ...(canDelete ? [{ key: "delete", label: "Delete", kind: "danger" as const, icon: ico("M5 7h14M10 11v6M14 11v6M7 7l1 13h8l1-13M9 7V4h6v3"), disabled: close.busy,
      onClick: () => {
        if (!window.confirm(`Delete deal "${d.name}"? This cannot be undone.`)) return;
        void close.run(async () => { await api.deleteDeal(ws.slug, d.id); return true; }).then((r) => { if (r) nav(`${base}/deals`); });
      } }] : []),
  ];
  const facts = (
    <div className="card">
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
    </div>
  );
  const peopleCard = (
    <div className="card">
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
    </div>
  );
  const tasks = (
    <div className="card stack">
      <h2>Tasks</h2>
      <TaskList dealId={d.id} refreshKey={tick} onChanged={() => setTick((n) => n + 1)} />
    </div>
  );
  const timeline = (
    <div className="card stack">
      <h2>Timeline</h2>
      <Timeline scope="deals" id={d.id} refreshKey={tick} />
    </div>
  );
  const meetingsCard = (
    <div className="card stack">
      <h2>Meetings</h2>
      <ErrorNote error={meetings.error} />
      {meetings.data && mine.length === 0 && <Empty>No meeting tied to this deal.</Empty>}
      {mine.length > 0 && <MeetingTable docs={mine} showAccount={false} onView={setViewing} onDelete={setDeleting} />}
    </div>
  );
  return (
    <>
      <RecordPage
        crumb={<><Link to={`${base}/deals`}>Deals</Link> / {d.name}</>}
        title={d.name}
        tags={<><Tag>{label(d.stage)}</Tag><Tag kind="mute">{d.source}</Tag></>}
        actions={actions}
        fields={[
          { label: "Amount", value: formatEur(d.amount_eur) },
          { label: "Stage", value: label(d.stage) },
          { label: "Created", value: d.created_on },
          { label: "Close date", value: d.closed_on ?? "—" },
        ]}
        owner={{ label: "Owner", value: d.owner_name ?? "—" }}
        process={<ProcessBar stage={d.stage} name={d.name} />}
        tab={tab} onTab={setTab}
        tabs={[
          { key: "summary", label: "Summary", content: (
            <SummaryLayout main={<>{facts}{peopleCard}{tasks}</>}
              side={<>{timeline}<div className="card stack"><h2>AI assistance</h2>
                <DealAiPanel ws={ws.slug} dealId={d.id} onChanged={() => setTick((n) => n + 1)} /></div></>} />
          ) },
          { key: "activity", label: "Activity", content: (
            <div className="stack">
              <div className="card stack" id="deal-activity">
                <h2>Stage and activity</h2>
                <StageControl deal={d} onMoved={() => { deal.reload(); setTick((n) => n + 1); }} />
                <h3>Log a call, email or meeting</h3>
                <ActivityPanel deal={d} contacts={people.data?.items ?? []} onLogged={() => setTick((n) => n + 1)} />
              </div>
              {timeline}
            </div>
          ) },
          { key: "emails", label: "Emails and meetings", content: (
            <div className="stack">
              <div className="card stack">
                <h2>Emails</h2>
                <DealEmailsPanel ws={ws.slug} dealId={d.id} onLinked={() => setTick((n) => n + 1)} />
              </div>
              {meetingsCard}
            </div>
          ) },
        ]}
      >
        <ErrorNote error={close.error} />
      </RecordPage>
      {editing && <DealForm deal={d} onClose={() => setEditing(false)} onSaved={deal.reload} />}
      {viewing && <TranscriptDialog id={viewing} onClose={() => setViewing(null)} />}
      {deleting && <DeleteMeeting doc={deleting} onClose={() => setDeleting(null)} onDone={meetings.reload} />}
    </>
  );
}
