import { Link } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { Icon, type IconName } from "../icons";
import { formatEur, formatStat, label } from "../lib";
import { isoDay, loadAllMeetings, splitByToday } from "../meetings/all";
import { HealthBar } from "../quality/HealthBar";
import { qualityApi } from "../quality/api";
import { DEAL_STAGES, type PipelineOut, type ScanOut } from "../types";
import { ApiError } from "../lib";
import { Empty, ErrorNote, Loading, Tag, useLoad } from "../ui";
import "./summary.css";

/** The latest scan, or null when none was run yet (404). */
async function latestScan(ws: string): Promise<ScanOut | null> {
  try { return await api.latestScan(ws); } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** Workspace dashboard: exact counts from SQL, the latest verified rate, data quality, meetings. */
export function SummaryPage() {
  const { ws } = useWs();
  const pipe = useLoad(() => api.pipeline(ws.slug), [ws.slug]);
  const scan = useLoad(() => latestScan(ws.slug), [ws.slug]);
  const quality = useLoad(() => qualityApi.get(ws.slug), [ws.slug]);
  const meetings = useLoad(() => loadAllMeetings(ws.slug), [ws.slug]);
  const base = `/w/${ws.slug}`;
  const p = pipe.data;
  const today = isoDay(new Date());
  const split = meetings.data ? splitByToday(meetings.data.items, today) : null;
  const winRate = scan.data?.report.overall.win_rate;

  return (
    <section className="stack summary">
      <header className="summary-hero tile">
        <p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</p>
        <h1>{ws.name}</h1>
        <p className="muted">Exact counts come straight from the database. Rates come from the latest analysis, with their interval and status.</p>
      </header>

      <ErrorNote error={pipe.error} />
      <div className="bento">
        <Kpi icon="deals" label="Open deals" value={p?.n_open} to={`${base}/deals`} />
        <Kpi icon="accounts" label="Won" value={p?.n_won} sub={p ? `${p.n_lost} lost` : undefined} to={`${base}/deals`} />
        <Kpi icon="stats" label="Pipeline amount" text={p ? formatEur(p.total_amount_eur) : undefined} sub={p ? `${p.n_deals} deals in total` : undefined} to={`${base}/deals`} />
        <div className="tile w3">
          <div className="tile-head"><span className="eyebrow">Win rate</span><span className="icon-badge"><Icon name="analysis" /></span></div>
          {scan.loading && !scan.data ? <Loading /> : winRate ? (
            <>
              <span className={`stat${winRate.status === "verified" ? "" : " nv"}`}>{formatStat(winRate, scan.data?.report.gates.confidence)}</span>
              <span>{winRate.status === "verified" ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">not verified</Tag>}</span>
            </>
          ) : <span className="stat-sub">No analysis yet.</span>}
          <Link className="small" to={`${base}/analysis/scan`}>Open the analysis</Link>
        </div>

        <div className="tile w8">
          <div className="tile-head"><h2 className="tile-title"><Icon name="stats" />Pipeline by stage</h2><Tag kind="mute">exact count</Tag></div>
          {!p ? <Loading /> : <StageBars p={p} />}
        </div>

        <div className="tile w4">
          <div className="tile-head"><h2 className="tile-title"><Icon name="meetings" />Next meetings</h2>
            <Link className="small" to={`${base}/meetings`}>Calendar</Link></div>
          <ErrorNote error={meetings.error} />
          {!split ? <Loading /> : split.upcoming.length === 0 ? (
            <>
              <Empty>No upcoming meeting.</Empty>
              {split.past.length > 0 && <p className="eyebrow">Latest</p>}
              <MeetingRows docs={split.past.slice(0, 4)} base={base} />
            </>
          ) : <MeetingRows docs={split.upcoming.slice(0, 5)} base={base} />}
        </div>

        <div className="tile w8">
          <div className="tile-head"><h2 className="tile-title"><Icon name="admin" />Data quality</h2></div>
          <ErrorNote error={quality.error} />
          {quality.loading && !quality.data ? <Loading /> : quality.data && (
            <div className="dq-grid">{quality.data.checks.map((c) => <HealthBar key={c.id} label={c.label} total={c.total} segments={c.segments} />)}</div>
          )}
        </div>

        <div className="tile w4 shortcuts">
          <h2>Shortcuts</h2>
          <Shortcut to={`${base}/analysis`} icon="analysis" text="Build an analysis flow" />
          <Shortcut to={`${base}/companies`} icon="companies" text="Look up a company" />
          <Shortcut to={`${base}/contacts`} icon="contacts" text="Review job titles" />
          <Shortcut to={`${base}/docs`} icon="docs" text="What the warnings mean" />
        </div>
      </div>
    </section>
  );
}

function Kpi(props: { icon: IconName; label: string; value?: number; text?: string; sub?: string; to: string }) {
  const shown = props.text ?? props.value?.toLocaleString();
  return (
    <Link to={props.to} className="tile w3 kpi-tile">
      <div className="tile-head"><span className="eyebrow">{props.label}</span><span className="icon-badge"><Icon name={props.icon} /></span></div>
      <span className="stat">{shown ?? "…"}</span>
      {props.sub && <span className="stat-sub">{props.sub}</span>}
    </Link>
  );
}

/** Horizontal bars, one per stage: deal count (exact) with the amount beside it. */
function StageBars({ p }: { p: PipelineOut }) {
  const rows = DEAL_STAGES.map((s) => ({ s, t: p.by_stage[s] })).filter((r) => r.t);
  const max = Math.max(1, ...rows.map((r) => r.t?.count ?? 0));
  if (rows.length === 0) return <Empty>No deals yet.</Empty>;
  return (
    <ul className="stagebars" aria-label="Deals per stage">
      {rows.map(({ s, t }) => (
        <li key={s}>
          <span className="sb-label">{label(s)}</span>
          <svg className={`sb-bar ${s === "closed_won" ? "won" : s === "closed_lost" ? "lost" : ""}`} viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
            <rect x="0" y="0" width="100" height="8" rx="4" className="sb-track" />
            <rect x="0" y="0" width={Math.max(2, ((t?.count ?? 0) / max) * 100)} height="8" rx="4" />
          </svg>
          <span className="num sb-n">{t?.count}</span>
          <span className="num muted small sb-amt">{formatEur(t?.amount_eur ?? 0)}</span>
        </li>
      ))}
    </ul>
  );
}

function MeetingRows({ docs, base }: { docs: { id: string; title: string; account_id: string; account_name: string; meeting_date: string | null }[]; base: string }) {
  return (
    <ul className="list-rows">{docs.map((d) => (
      <li key={d.id}>
        <Link className="row-link" to={`${base}/accounts/${d.account_id}`}>
          <span className="date-chip">{shortDay(d.meeting_date)}</span>
          <span className="grow"><span className="ellipsis">{d.title}</span><span className="muted small ellipsis">{d.account_name}</span></span>
          <Icon name="chevron" size={16} className="chev" />
        </Link>
      </li>
    ))}</ul>
  );
}

function Shortcut({ to, icon, text }: { to: string; icon: IconName; text: string }) {
  return <Link className="row-link" to={to}><span className="icon-badge"><Icon name={icon} /></span><span className="grow">{text}</span><Icon name="arrow" size={16} className="chev" /></Link>;
}

/** "20 Oct" for the date chip. */
function shortDay(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(t.getTime()) ? "—" : t.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
