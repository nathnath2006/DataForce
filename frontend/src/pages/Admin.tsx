import { useState } from "react";
import { adminApi } from "../admin/api";
import { formatBytes, formatDuration } from "../admin/format";
import { HealthBar } from "../quality/HealthBar";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import { People } from "../admin/People";
import { Limits } from "../admin/Limits";
import { Usage } from "../admin/Usage";
import { AccessCodes } from "../admin/AccessCodes";
import { useAuth } from "../auth";
import { Empty, ErrorNote, Loading, Tag, useLoad } from "../ui";

const KINDS = ["demo_generate", "stats_scan", "flow_run", "title_normalize", "org_rules", "theme_analysis", "agent_call"];
const STATUSES = ["running", "succeeded", "partial", "failed"];

export function AdminPage() {
  const { ws } = useWs();
  const { isAdmin, user } = useAuth();
  const [globalLimits, setGlobalLimits] = useState(false);
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
      {isAdmin && <People slug={ws.slug} />}
      <div className="card stack">
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
      </div>

      <Usage ws={ws.slug} superadmin={!!user?.is_admin} />
      <AccessCodes ws={ws.slug} superadmin={!!user?.is_admin} />

      <div className="card stack">
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
      </div>

      <div className="stack">
        {user?.is_admin && (
          <label>Limits for
            <select value={globalLimits ? "global" : "ws"} onChange={(e) => setGlobalLimits(e.target.value === "global")}>
              <option value="ws">This workspace</option><option value="global">All workspaces (global)</option>
            </select>
          </label>
        )}
        <Limits ws={user?.is_admin && globalLimits ? null : ws.slug} />
      </div>
    </section>
  );
}
