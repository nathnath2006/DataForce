import { useState } from "react";
import { useSearchParams } from "react-router";
import { adminApi } from "../admin/api";
import { formatBytes, formatDuration } from "../admin/format";
import { HealthBar } from "../quality/HealthBar";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import { People } from "../admin/People";
import { Limits } from "../admin/Limits";
import { Usage } from "../admin/Usage";
import { AccessCodes } from "../admin/AccessCodes";
import { DemoBlockedNote, useAuth } from "../auth";
import "../analysis/analysis.css";
import { Empty, ErrorNote, Loading, Tag, useLoad } from "../ui";

const KINDS = ["demo_generate", "stats_scan", "flow_run", "title_normalize", "org_rules", "theme_analysis", "agent_call"];
const STATUSES = ["running", "succeeded", "partial", "failed"];

export function AdminPage() {
  const { ws } = useWs();
  const { isAdmin, user, isDemo } = useAuth();
  const [globalLimits, setGlobalLimits] = useState(false);
  const [sp, setSp] = useSearchParams();
  const tabs = [
    ...(isAdmin ? [["people", "People and access"] as const] : []),
    ["usage", "Usage"], ["codes", "Access codes"], ["limits", "Limits"], ["database", "Database"], ["runs", "Recent runs"],
  ] as const;
  const want = sp.get("tab");
  const tab = tabs.some(([k]) => k === want) ? want : tabs[0][0];
  const pick = (k: string) => setSp((p) => { const n = new URLSearchParams(p); n.set("tab", k); return n; }, { replace: true });
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const ov = useLoad(() => adminApi.overview(ws.slug), [ws.slug]);
  const runs = useLoad(() => adminApi.runs(ws.slug, kind, status), [ws.slug, kind, status]);
  const db = ov.data?.database;
  const sc = ov.data?.schema_status;
  // The bar counts whole megabytes, so its "x of y" and key read as MB, not bytes.
  const quota = db ? db.quota_mb : 0;
  const used = db ? Math.min(Math.ceil(db.size_bytes / 1048576), quota) : 0;

  return (
    <section className="stack">
      <h1>Admin</h1>
      <div className="an-tabs" role="tablist" aria-label="Admin sections">
        {tabs.map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} className={`adm-tab${tab === k ? " active" : ""}`} onClick={() => pick(k)}>{l}</button>
        ))}
      </div>
      {tab === "people" && isAdmin && (isDemo ? <DemoBlockedNote title="People and access" /> : <People slug={ws.slug} />)}
      {tab === "database" && <div className="card stack">
        <h2>Database</h2>
        <ErrorNote error={ov.error} />
        {ov.loading && !db ? <Loading /> : db && sc && (
          <>
            <HealthBar
              label={`${formatBytes(db.size_bytes)} of ${db.quota_mb} MB (${db.used_pct ?? "—"}%)`}
              total={quota}
              segments={[
                { kind: db.used_pct != null && db.used_pct >= 90 ? "bad" : db.used_pct != null && db.used_pct >= 70 ? "warn" : "ok", label: "Used (MB)", count: used },
                { kind: "unknown", label: "Free (MB)", count: Math.max(0, quota - used) },
              ]}
            />
            <p>Schema: {sc.up_to_date
              ? <Tag kind="ok">up to date</Tag>
              : <Tag kind="warn">migration needed: run make migrate</Tag>}{" "}
              <span className="muted small">database {sc.current ?? "none"}, code {sc.head ?? "none"}</span></p>
            <div className="tablewrap">
              <table>
                <thead><tr><th>Table</th><th className="num">Size</th><th className="num">Rows (estimate)</th></tr></thead>
                <tbody>
                  {db.tables.slice(0, 15).map((t) => (
                    <tr key={t.name}><td>{t.name}</td><td className="num">{formatBytes(t.bytes)}</td><td className="num">{t.rows_estimate.toLocaleString()}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>}

      {tab === "usage" && <Usage ws={ws.slug} superadmin={!!user?.is_admin} />}
      {tab === "codes" && (isDemo ? <DemoBlockedNote title="Access codes" /> : <AccessCodes ws={ws.slug} superadmin={!!user?.is_admin} />)}

      {tab === "runs" && <div className="card stack">
        <div className="row between">
          <h2>Recent runs</h2>
          <span className="row">
            <select aria-label="Kind" value={kind} onChange={(ev) => setKind(ev.target.value)}>
              <option value="">All kinds</option>{KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <select aria-label="Status" value={status} onChange={(ev) => setStatus(ev.target.value)}>
              <option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </span>
        </div>
        <ErrorNote error={runs.error} />
        {runs.loading && !runs.data ? <Loading /> : runs.data && (runs.data.runs.length === 0 ? <Empty>No runs.</Empty> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Kind</th><th>Status</th><th>Started</th><th className="num">Duration</th><th>Error</th><th>Summary</th></tr></thead>
            <tbody>{runs.data.runs.map((r) => (
              <tr key={r.id}><td>{r.kind}</td>
                <td><Tag kind={r.status === "succeeded" ? "ok" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Tag>{r.stale && <> <Tag kind="bad">stale</Tag></>}</td>
                <td>{formatDateTime(r.started_at)}</td><td className="num">{formatDuration(r.duration_ms)}</td>
                <td className="pre">{r.error ?? ""}</td><td>{r.summary}</td></tr>
            ))}</tbody>
          </table></div>
        ))}
      </div>}

      {tab === "limits" && (
        <Limits ws={user?.is_admin && globalLimits ? null : ws.slug} readOnly={isDemo}
          scope={user?.is_admin ? (globalLimits ? "global" : "ws") : undefined} onScope={(v) => setGlobalLimits(v === "global")} />
      )}
    </section>
  );
}
