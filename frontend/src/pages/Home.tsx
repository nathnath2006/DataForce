import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { useAuth, useSeesAll } from "../auth";
import { useWs } from "../context";
import { listKey, useQuery } from "../data/useQuery";
import { homeApi, type HomeActivity, type HomeDeal, type HomeOut, type HomeStage, type HomeStalledDeal, type HomeTask } from "../home/api";
import { Icon, type IconName } from "../icons";
import { ago, relDay } from "../home/dates";
import { ApiError, formatEur, formatStat, label } from "../lib";
import { isoDay, loadAllMeetings, splitByToday } from "../meetings/all";
import { HealthBar } from "../quality/HealthBar";
import { qualityApi } from "../quality/api";
import type { ScanOut } from "../types";
import { ErrorNote, Loading, Tag, useLoad } from "../ui";
import "../home/home.css";

const ROWS = 5; // every card shows a few rows, then a link to the full list
const OPEN = ["prospecting", "qualification", "proposal", "negotiation"];

/** The latest scan, or null when none was run yet (404). */
async function latestScan(ws: string): Promise<ScanOut | null> {
  try { return await api.latestScan(ws); } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/**
 * Home (Home and Summary merged): what to do now first (tasks, stalled deals), then where the pipeline
 * stands. Every card is bounded: a few rows and a link to the full list, never an endless column.
 */
export function HomePage() {
  const { ws, users } = useWs();
  const { user } = useAuth();
  const seesAll = useSeesAll();
  const [owner, setOwner] = useState("");
  const home = useQuery(listKey(ws.slug, "home", { owner }), (signal) => homeApi.get(ws.slug, owner || undefined, signal));
  const scan = useLoad(() => latestScan(ws.slug), [ws.slug]);
  const quality = useLoad(() => qualityApi.get(ws.slug, owner || undefined), [ws.slug, owner]);
  const meetings = useLoad(() => loadAllMeetings(ws.slug), [ws.slug]);
  const base = `/w/${ws.slug}`;
  const ownerQ = owner ? `&owner_id=${owner}` : "";
  const data = home.data;
  const first = user?.display_name.split(" ")[0];
  const ownerName = users.find((u) => u.id === owner)?.display_name;
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

  return (
    <section className="home">
      <header className="home-head">
        <div>
          <p className="eyebrow">{today} · {ws.name}</p>
          <h1>{first ? `Hello, ${first}` : "Home"}</h1>
          <p className="muted">{ownerName ? `${ownerName}'s pipeline and tasks.` : seesAll ? "Everyone's work in this workspace." : "Your work at a glance."}</p>
        </div>
        <div className="home-tools">
          {seesAll && (
            <select aria-label="Whose numbers" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Everyone</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
            </select>
          )}
          <Link className="hm-btn-link" to={`${base}/tasks`}><Icon name="plus" size={16} />Task</Link>
          <Link className="hm-btn-link primary" to={`${base}/deals`}><Icon name="plus" size={16} />Deal</Link>
        </div>
      </header>

      <ErrorNote error={home.error} />
      {home.loading && !data && <Loading />}
      {data && (
        <>
          <Kpis data={data} base={base} ownerQ={ownerQ} scan={scan.data} scanLoading={scan.loading && !scan.data} />
          <div className="home-grid">
            <TasksCard tasks={data.tasks} overdue={data.kpis.tasks_overdue} dueWeek={data.kpis.tasks_due_week} base={base} />
            <PipelineCard stages={data.by_stage} base={base} ownerQ={ownerQ} />
            <DealsCard data={data} base={base} ownerQ={ownerQ} showOwner={!owner && seesAll} />
            <Card cls="c5" icon="meetings" title="Up next" foot={<Link to={`${base}/meetings`}>Calendar <Icon name="arrow" size={14} /></Link>}>
              <ErrorNote error={meetings.error} />
              {!meetings.data ? <Loading /> : <Meetings items={meetings.data.items} base={base} />}
            </Card>
            <ActivityCard items={data.activity} base={base} />
            <Card cls="c5" icon="admin" title="Data health" foot={<Link to={`${base}/docs`}>What the warnings mean <Icon name="arrow" size={14} /></Link>}>
              <ErrorNote error={quality.error} />
              {quality.loading && !quality.data ? <Loading /> : quality.data && (
                <div className="hm-dq">{quality.data.checks.map((c) => <HealthBar key={c.id} label={c.label} total={c.total} segments={c.segments} />)}</div>
              )}
            </Card>
          </div>
        </>
      )}
    </section>
  );
}

// --- building blocks ------------------------------------------------------------------------------
function Card(p: { cls: string; icon: IconName; title: string; tools?: ReactNode; foot?: ReactNode; children: ReactNode }) {
  return (
    <div className={`hm-card ${p.cls}`}>
      <div className="hm-card-head"><h2><Icon name={p.icon} size={18} />{p.title}</h2>{p.tools}</div>
      {p.children}
      {p.foot && <div className="hm-card-foot">{p.foot}</div>}
    </div>
  );
}

function Seg<K extends string>(p: { value: K; onChange: (k: K) => void; options: { key: K; label: string; count?: number; alert?: boolean }[] }) {
  return (
    <div className="hm-seg" role="tablist">
      {p.options.map((o) => (
        <button key={o.key} type="button" role="tab" aria-selected={p.value === o.key} className={o.alert ? "alert" : ""} onClick={() => p.onChange(o.key)}>
          {o.label}{o.count !== undefined && <span className="count">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

function initials(name: string | null | undefined): string {
  if (!name) return "—";
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");
}

const n = (v: number) => v.toLocaleString("en-US");

// --- KPI strip --------------------------------------------------------------------------------------
function Kpis(p: { data: HomeOut; base: string; ownerQ: string; scan: ScanOut | null | undefined; scanLoading: boolean }) {
  const k = p.data.kpis;
  const win = p.scan?.report.overall.win_rate;
  return (
    <div className="hm-kpis">
      <Kpi to={`${p.base}/deals?sort=amount_eur&dir=desc${p.ownerQ}`} icon="deals" label="Open pipeline" value={formatEur(k.open_pipeline_eur)}
        sub={`${n(k.open_deals)} open ${k.open_deals === 1 ? "deal" : "deals"}`} />
      <Kpi to={`${p.base}/deals?stage=closed_won${p.ownerQ}`} icon="accounts" label="Won this quarter" value={formatEur(k.won_this_quarter_eur)}
        sub={`${n(k.won_this_quarter)} ${k.won_this_quarter === 1 ? "deal" : "deals"}`} />
      <Kpi to={`${p.base}/tasks`} icon="calendar" label="Tasks this week" value={n(k.tasks_due_week)}
        sub={k.tasks_overdue > 0 ? `${n(k.tasks_overdue)} overdue` : "none overdue"} bad={k.tasks_overdue > 0} />
      <Link to={`${p.base}/analysis/scan`} className="hm-kpi">
        <div className="hm-kpi-top"><p className="hm-kpi-label">Win rate · workspace</p><span className="icon-badge"><Icon name="analysis" size={16} /></span></div>
        {p.scanLoading ? <span className="hm-kpi-value nv">…</span> : win ? (
          <>
            <span className={`hm-kpi-value${win.status === "verified" ? "" : " nv"}`}>{formatStat(win, p.scan?.report.gates.confidence)}</span>
            <span className="hm-kpi-sub">{win.status === "verified" ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">not verified</Tag>}latest scan</span>
          </>
        ) : (<><span className="hm-kpi-value nv">No scan yet</span><span className="hm-kpi-sub">Run the pipeline scan</span></>)}
      </Link>
    </div>
  );
}

function Kpi(p: { to: string; icon: IconName; label: string; value: string; sub: string; bad?: boolean }) {
  return (
    <Link to={p.to} className="hm-kpi">
      <div className="hm-kpi-top"><p className="hm-kpi-label">{p.label}</p><span className="icon-badge"><Icon name={p.icon} size={16} /></span></div>
      <span className="hm-kpi-value">{p.value}</span>
      <span className={`hm-kpi-sub${p.bad ? " bad" : ""}`}>{p.sub}</span>
    </Link>
  );
}

// --- tasks: what to do now -------------------------------------------------------------------------
function TasksCard(p: { tasks: HomeTask[]; overdue: number; dueWeek: number; base: string }) {
  const [tab, setTab] = useState<"overdue" | "week">(p.overdue > 0 ? "overdue" : "week");
  const shown = p.tasks.filter((t) => (tab === "overdue" ? t.overdue : !t.overdue)).slice(0, ROWS);
  const total = tab === "overdue" ? p.overdue : p.dueWeek;
  return (
    <Card cls="c5" icon="calendar" title="Focus"
      tools={<Seg value={tab} onChange={setTab} options={[
        { key: "overdue", label: "Overdue", count: p.overdue, alert: p.overdue > 0 },
        { key: "week", label: "This week", count: p.dueWeek }]} />}
      foot={<Link to={`${p.base}/tasks`}>{total > shown.length ? `${n(total - shown.length)} more in Tasks` : "All tasks"} <Icon name="arrow" size={14} /></Link>}>
      {shown.length === 0 ? <p className="hm-empty-card">{tab === "overdue" ? "Nothing overdue. Nice." : "Nothing else due this week."}</p> : (
        <ul className="hm-rows">{shown.map((t) => {
          const to = t.deal_id ? `${p.base}/deals/${t.deal_id}` : t.account_id ? `${p.base}/accounts/${t.account_id}` : `${p.base}/tasks`;
          return (
            <li key={t.id}>
              <Link className="hm-row" to={to}>
                <span className={`hm-dot${t.overdue ? " overdue" : ""}`}><Icon name="calendar" size={15} /></span>
                <span className="hm-row-main"><span className="hm-row-title">{t.title}</span><span className="hm-row-sub">{t.deal_name ?? t.account_name ?? "No deal"}</span></span>
                <span className="hm-row-end"><span className={t.overdue ? "over" : ""}>{relDay(t.due_on)}</span></span>
              </Link>
            </li>
          );
        })}</ul>
      )}
    </Card>
  );
}

// --- pipeline funnel ---------------------------------------------------------------------------------
function PipelineCard(p: { stages: HomeStage[]; base: string; ownerQ: string }) {
  const open = p.stages.filter((s) => OPEN.includes(s.stage));
  const won = p.stages.find((s) => s.stage === "closed_won");
  const lost = p.stages.find((s) => s.stage === "closed_lost");
  const max = Math.max(1, ...open.map((s) => Number(s.amount_eur)));
  return (
    <Card cls="c7" icon="stats" title="Pipeline by stage" tools={<Tag kind="mute">exact, from the database</Tag>}
      foot={<Link to={`${p.base}/deals`}>Open the board <Icon name="arrow" size={14} /></Link>}>
      <ul className="hm-funnel" aria-label="Open deals per stage">
        {open.map((s) => (
          <li key={s.stage}>
            <Link to={`${p.base}/deals?stage=${s.stage}${p.ownerQ}`} title={`${s.count} deals in ${label(s.stage)}`}>
              <span className="f-label">{label(s.stage)}</span>
              <span className="f-track"><span className="f-bar" style={{ width: `${Math.max(2, (Number(s.amount_eur) / max) * 100)}%` }} /></span>
              <span className="f-n">{n(s.count)}</span>
              <span className="f-amt">{formatEur(s.amount_eur)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <div className="hm-closed">
        <Link className="won" to={`${p.base}/deals?stage=closed_won${p.ownerQ}`}><span>Won</span><b>{n(won?.count ?? 0)}</b><span className="muted">{formatEur(won?.amount_eur ?? 0)}</span></Link>
        <Link className="lost" to={`${p.base}/deals?stage=closed_lost${p.ownerQ}`}><span>Lost</span><b>{n(lost?.count ?? 0)}</b><span className="muted">{formatEur(lost?.amount_eur ?? 0)}</span></Link>
      </div>
    </Card>
  );
}

// --- deals to work on --------------------------------------------------------------------------------
function DealsCard(p: { data: HomeOut; base: string; ownerQ: string; showOwner: boolean }) {
  const stalled = p.data.stalled_deals;
  const [tab, setTab] = useState<"top" | "stalled" | "new">("top");
  const rows: (HomeDeal | HomeStalledDeal)[] = (tab === "top" ? p.data.top_deals : tab === "stalled" ? stalled : p.data.open_deals).slice(0, ROWS);
  const all = tab === "top" ? `?sort=amount_eur&dir=desc${p.ownerQ}` : tab === "new" ? `?sort=created_on&dir=desc${p.ownerQ}` : p.ownerQ ? `?${p.ownerQ.slice(1)}` : "";
  return (
    <Card cls="c7" icon="deals" title="Deals to work on"
      tools={<Seg value={tab} onChange={setTab} options={[
        { key: "top", label: "Biggest" },
        { key: "stalled", label: "Stalling", count: p.data.stalled_total, alert: p.data.stalled_total > 0 },
        { key: "new", label: "Newest" }]} />}
      foot={<Link to={`${p.base}/deals${all}`}>{tab === "stalled" && p.data.stalled_total > rows.length ? `${n(p.data.stalled_total - rows.length)} more stalling · all deals` : "All deals"} <Icon name="arrow" size={14} /></Link>}>
      {rows.length === 0 ? <p className="hm-empty-card">{tab === "stalled" ? "No deal has been stuck for 30 days." : "No open deal."}</p> : (
        <ul className="hm-rows">{rows.map((d) => (
          <li key={d.id}>
            <Link className="hm-row" to={`${p.base}/deals/${d.id}`}>
              <span className="hm-avatar" title={d.owner_name ?? "No owner"}>{initials(d.owner_name)}</span>
              <span className="hm-row-main">
                <span className="hm-row-title">{d.name}</span>
                <span className="hm-row-sub">{d.account_name}{p.showOwner && d.owner_name ? ` · ${d.owner_name}` : ""}</span>
              </span>
              <span className="hm-row-end">
                <span className="amt">{d.amount_eur == null ? "—" : formatEur(d.amount_eur)}</span>
                {"days_in_stage" in d
                  ? <span className="hm-pill stall">{d.days_in_stage} days in {label(d.stage).toLowerCase()}</span>
                  : <span className={`hm-pill s-${d.stage}`}>{label(d.stage)}</span>}
              </span>
            </Link>
          </li>
        ))}</ul>
      )}
    </Card>
  );
}

// --- meetings ----------------------------------------------------------------------------------------
function Meetings({ items, base }: { items: { id: string; title: string; account_id: string; account_name: string; meeting_date: string | null }[]; base: string }) {
  const split = splitByToday(items as Parameters<typeof splitByToday>[0], isoDay(new Date()));
  const upcoming = split.upcoming.slice(0, 4);
  const rows = upcoming.length ? upcoming : split.past.slice(0, 4);
  if (rows.length === 0) return <p className="hm-empty-card">No meeting yet.</p>;
  return (
    <>
      {!upcoming.length && <p className="eyebrow">No upcoming meeting · latest</p>}
      <ul className="hm-rows">{rows.map((d) => (
        <li key={d.id}>
          <Link className="hm-row" to={`${base}/accounts/${d.account_id}`}>
            <DateTile iso={d.meeting_date} />
            <span className="hm-row-main"><span className="hm-row-title">{d.title}</span><span className="hm-row-sub">{d.account_name}</span></span>
            <Icon name="chevron" size={16} className="chev" />
          </Link>
        </li>
      ))}</ul>
    </>
  );
}

function DateTile({ iso }: { iso: string | null }) {
  const t = iso ? new Date(iso.length === 10 ? `${iso}T12:00:00` : iso) : null;
  if (!t || Number.isNaN(t.getTime())) return <span className="hm-date-tile"><b>—</b></span>;
  return <span className="hm-date-tile"><b>{t.getDate()}</b><span>{t.toLocaleDateString("en-GB", { month: "short" })}</span></span>;
}

// --- activity -----------------------------------------------------------------------------------------
const KIND_ICON: Record<string, IconName> = { stage: "arrow", call: "send", email: "mail", meeting: "meetings", task: "edit", other: "history" };

function ActivityCard({ items, base }: { items: HomeActivity[]; base: string }) {
  const [more, setMore] = useState(false);
  const shown = items.slice(0, more ? items.length : ROWS);
  return (
    <Card cls="c7" icon="history" title="Recent activity"
      foot={items.length > ROWS ? <button type="button" className="hm-linklike" onClick={() => setMore((m) => !m)}>{more ? "Show less" : `Show ${items.length - ROWS} more`}</button> : undefined}>
      {shown.length === 0 ? <p className="hm-empty-card">No activity on these deals yet.</p> : (
        <ul className="hm-rows">{shown.map((a) => (
          <li key={a.id}>
            <Link className="hm-row" to={`${base}/deals/${a.deal_id}`}>
              <span className={`hm-dot k-${a.kind}`}><Icon name={KIND_ICON[a.kind] ?? "history"} size={15} /></span>
              <span className="hm-row-main"><span className="hm-row-title">{a.title}</span><span className="hm-row-sub">{a.deal_name}{a.author_name ? ` · ${a.author_name}` : ""}</span></span>
              <span className="hm-row-end"><span className="muted">{ago(a.at)}</span></span>
            </Link>
          </li>
        ))}</ul>
      )}
    </Card>
  );
}
