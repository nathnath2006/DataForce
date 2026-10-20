import { useState } from "react";
import { Link } from "react-router";
import { useAuth, useSeesAll } from "../auth";
import { useWs } from "../context";
import { listKey, useQuery } from "../data/useQuery";
import { formatDate, formatDateTime, formatEur, label } from "../lib";
import { homeApi } from "../home/api";
import { ErrorNote, Loading } from "../ui";
import "../home/home.css";

function Kpi(p: { label: string; value: string; sub?: string; bad?: boolean }) {
  return (
    <div className="kpi">
      <p className="kpi-label">{p.label}</p>
      <p className="kpi-value">{p.value}</p>
      {p.sub && <p className={`kpi-sub ${p.bad ? "bad" : ""}`}>{p.sub}</p>}
    </div>
  );
}

/** Home: a calm summary of the signed-in member's work. The admin (and *see all* members) can look at one rep. */
export function HomePage() {
  const { ws, users } = useWs();
  const { user } = useAuth();
  const seesAll = useSeesAll();
  const [owner, setOwner] = useState("");
  const { data, error, loading } = useQuery(listKey(ws.slug, "home", { owner }), (signal) => homeApi.get(ws.slug, owner || undefined, signal));
  const base = `/w/${ws.slug}`;
  const k = data?.kpis;
  const first = user?.display_name.split(" ")[0];
  return (
    <section className="home">
      <div className="home-head">
        <div>
          <h1>{first ? `Hello, ${first}` : "Home"}</h1>
          <p className="muted">{owner ? "One rep's numbers." : seesAll ? "Everyone's work in this workspace." : "Your work at a glance."}</p>
        </div>
        {seesAll && (
          <select aria-label="Sales rep" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Everyone</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        )}
      </div>
      <ErrorNote error={error} />
      {loading && !data && <Loading />}
      {data && k && (
        <>
          <div className="kpis">
            <Kpi label="Open deals" value={k.open_deals.toLocaleString("en-US")} />
            <Kpi label="Open pipeline" value={formatEur(k.open_pipeline_eur)} />
            <Kpi label="Won this quarter" value={formatEur(k.won_this_quarter_eur)}
              sub={`${k.won_this_quarter.toLocaleString("en-US")} ${k.won_this_quarter === 1 ? "deal" : "deals"}`} />
            <Kpi label="Tasks due this week" value={k.tasks_due_week.toLocaleString("en-US")}
              sub={k.tasks_overdue > 0 ? `${k.tasks_overdue.toLocaleString("en-US")} overdue` : "none overdue"} bad={k.tasks_overdue > 0} />
          </div>
          <div className="home-grid">
            <div className="home-card">
              <h2>Open deals</h2>
              {data.open_deals.length === 0 ? <p className="muted">No open deal.</p> : (
                <ul className="home-list">
                  {data.open_deals.map((d) => (
                    <li key={d.id}>
                      <span className="hl-main">
                        <Link to={`${base}/deals/${d.id}`}>{d.name}</Link>
                        <span className="hl-sub">{d.account_name} · {label(d.stage)}{!owner && d.owner_name ? ` · ${d.owner_name}` : ""}</span>
                      </span>
                      <span className="hl-val">{formatEur(d.amount_eur)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="small"><Link to={`${base}/deals`}>All deals</Link></p>
            </div>
            <div className="home-card">
              <h2>Tasks due</h2>
              {data.tasks.length === 0 ? <p className="muted">Nothing due this week.</p> : (
                <ul className="home-list">
                  {data.tasks.map((t) => (
                    <li key={t.id}>
                      <span className="hl-main">
                        <span className="t">{t.title}</span>
                        <span className="hl-sub">
                          {t.deal_id ? <Link to={`${base}/deals/${t.deal_id}`}>{t.deal_name}</Link> : t.account_name}
                        </span>
                      </span>
                      <span className={`hl-val ${t.overdue ? "hl-over" : ""}`}>{t.overdue ? "Overdue · " : ""}{formatDate(t.due_on)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="small"><Link to={`${base}/tasks`}>All tasks</Link></p>
            </div>
            <div className="home-card wide">
              <h2>Recent activity</h2>
              {data.activity.length === 0 ? <p className="muted">No activity on your deals yet.</p> : (
                <ul className="home-list">
                  {data.activity.map((a) => (
                    <li key={a.id}>
                      <span className="hl-main">
                        <span className="t">{a.title}</span>
                        <span className="hl-sub"><Link to={`${base}/deals/${a.deal_id}`}>{a.deal_name}</Link>{a.author_name ? ` · ${a.author_name}` : ""}</span>
                      </span>
                      <span className="hl-val">{label(a.kind)} · {formatDateTime(a.at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
