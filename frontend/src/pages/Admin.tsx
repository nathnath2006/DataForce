import { Fragment, useState } from "react";
import { adminApi } from "../admin/api";
import { formatBytes, formatDuration, purposeLabel } from "../admin/format";
import { HealthBar } from "../quality/HealthBar";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import { Empty, ErrorNote, Loading, Tag, useLoad } from "../ui";

const KINDS = ["demo_generate", "stats_scan", "flow_run", "title_normalize", "org_rules", "theme_analysis", "agent_call"];
const STATUSES = ["running", "succeeded", "partial", "failed"];

export function AdminPage() {
  const { ws } = useWs();
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const ov = useLoad(() => adminApi.overview(ws.slug), [ws.slug]);
  const usage = useLoad(() => adminApi.usage(ws.slug, days), [ws.slug, days]);
  const runs = useLoad(() => adminApi.runs(ws.slug, kind, status), [ws.slug, kind, status]);
  const db = ov.data?.database;
  const sc = ov.data?.schema_status;
  // The bar counts whole megabytes, so its "x of y" and key read as MB, not bytes.
  const quota = db ? db.quota_mb : 0;
  const used = db ? Math.min(Math.ceil(db.size_bytes / 1048576), quota) : 0;

  return (
    <section className="stack">
      <h1>Admin</h1>
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

      <div className="card stack">
        <div className="row between">
          <h2>AI usage</h2>
          <select aria-label="Period" value={days} onChange={(ev) => setDays(Number(ev.target.value))}>
            {[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </div>
        <ErrorNote error={usage.error} />
        {usage.loading && !usage.data ? <Loading /> : usage.data && (
          <>
            <p className="muted small">From the llm_call table (persisted calls), not the in-memory budgets.</p>
            {usage.data.rows.length === 0 ? <Empty>No AI calls in this period.</Empty> : (
              <div className="tablewrap"><table>
                <thead><tr><th>Provider</th><th>Model</th><th>Purpose</th><th className="num">Calls</th><th className="num">Failures</th><th className="num">Tokens in</th><th className="num">Tokens out</th></tr></thead>
                <tbody>{usage.data.rows.map((r) => (
                  <tr key={`${r.provider}/${r.model}/${r.purpose}`}><td>{r.provider}</td><td>{r.model}</td><td>{purposeLabel(r.purpose)}</td>
                    <td className="num">{r.calls}</td><td className="num">{r.failures}</td>
                    <td className="num">{r.input_tokens.toLocaleString()}</td><td className="num">{r.output_tokens.toLocaleString()}</td></tr>
                ))}</tbody>
              </table></div>
            )}
            <h3>Today</h3>
            <div className="tablewrap"><table>
              <thead><tr><th>Purpose</th><th className="num">Calls today</th><th className="num">Daily cap</th></tr></thead>
              <tbody>{usage.data.today.map((t) => (
                <tr key={t.purpose}><td>{purposeLabel(t.purpose)}</td><td className="num">{t.calls}</td><td className="num">{t.daily_cap ?? "—"}</td></tr>
              ))}</tbody>
            </table></div>
          </>
        )}
      </div>

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

      <div className="card stack">
        <h2>Limits</h2>
        <p className="muted small">Read-only. These are set in backend/.env.</p>
        {ov.data && (
          <dl className="facts">
            {ov.data.limits.map((l) => (
              <Fragment key={l.name}><dt>{l.name}</dt><dd><strong>{l.value.toLocaleString()}</strong> <span className="muted small">{l.description}</span></dd></Fragment>
            ))}
          </dl>
        )}
      </div>
    </section>
  );
}
