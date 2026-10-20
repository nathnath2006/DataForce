import { ReasonList } from "../docs/Reasons";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useWs } from "../context";
import {
  formatDiffWithCi, formatNum, formatEur, formatPct, formatQ, formatStat, formatDateTime, label, unitOf,
} from "../lib";
import type { EffectFinding, GateConfig, Metric, ScanOut, StatValue } from "../types";
import { AnalysisTabs } from "../analysis/AnalysisTabs";
import { ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";

const METRIC_LABEL: Record<Metric, string> = {
  win_rate: "Win rate", cycle_days: "Median cycle", deal_amount: "Median deal amount",
};

export function AnalysisPage() {
  const { ws } = useWs();
  const pipe = useLoad(() => api.pipeline(ws.slug), [ws.slug]);
  const [scan, setScan] = useState<ScanOut | null>(null);
  const [none, setNone] = useState(false);
  const [loadingScan, setLoadingScan] = useState(true);
  const act = useAction();
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    let live = true;
    setScan(null); setNone(false); setLoadingScan(true); setErr(null);
    api.latestScan(ws.slug).then(
      (s) => { if (live) { setScan(s); setLoadingScan(false); } },
      (e: { status?: number }) => {
        if (!live) return;
        if (e.status === 404) setNone(true); else setErr(e);
        setLoadingScan(false);
      });
    return () => { live = false; };
  }, [ws.slug]);
  const run = () => act.run(async () => { setScan(await api.runScan(ws.slug)); setNone(false); pipe.reload(); });
  const r = scan?.report;
  return (
    <section className="stack">
      <AnalysisTabs />
      <div className="page-head">
        <h1>Pipeline scan</h1>
        <button className="primary" disabled={act.busy} onClick={() => void run()}>{act.busy ? "Running…" : "Run analysis"}</button>
      </div>

      <p className="muted">Compares groups of deals (owner, source, segment…) on win rate, cycle and deal size, and marks each difference verified only when a statistical test backs it.</p>

      <div className="tile">
        <h2>Pipeline <Tag kind="mute">exact count</Tag></h2>
        <ErrorNote error={pipe.error} />
        {pipe.data && (
          <>
            <p>
              {pipe.data.n_deals} deals · {pipe.data.n_open} open · {pipe.data.n_won} won · {pipe.data.n_lost} lost · total amount {formatEur(pipe.data.total_amount_eur)}
            </p>
            <div className="tablewrap"><table>
              <thead><tr><th>Stage</th><th className="num">Deals</th><th className="num">Amount</th><th className="num">With amount</th></tr></thead>
              <tbody>{Object.entries(pipe.data.by_stage).map(([s, t]) => t && (
                <tr key={s}><td>{label(s)}</td><td className="num">{t.count}</td><td className="num">{formatEur(t.amount_eur)}</td><td className="num">{t.n_with_amount}</td></tr>
              ))}</tbody>
            </table></div>
          </>
        )}
      </div>

      <ErrorNote error={act.error ?? err} />
      {loadingScan && !scan && <Loading />}
      {none && !scan && <p className="muted">No analysis has been run yet. Click “Run analysis”.</p>}
      {r && <ScanView report={r} />}
    </section>
  );
}

function ScanView({ report }: { report: NonNullable<ScanOut["report"]> }) {
  const [showNV, setShowNV] = useState(false);
  const verified = report.findings.filter((f) => f.status === "verified");
  const notVerified = report.findings.filter((f) => f.status !== "verified");
  const conf = report.gates.confidence;
  return (
    <>
      <p className="muted">
        Scan of {formatDateTime(report.created_at)}: {report.n_deals} deals ({report.n_closed} closed, {report.n_open} open).
      </p>
      <div className="tile">
        <h2>Overall</h2>
        <div className="tablewrap"><table>
          <thead><tr><th>Metric</th><th>Value (CI)</th><th className="num">n</th><th>Method</th><th>Status</th></tr></thead>
          <tbody>{(Object.entries(report.overall) as [Metric, StatValue][]).map(([m, s]) => (
            <tr key={m} className={s.status === "verified" ? "" : "nv"}>
              <td>{METRIC_LABEL[m]}</td><td>{formatStat(s, conf)}</td><td className="num">{s.n}</td><td>{s.method}</td>
              <td>{s.status === "verified" ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">not verified</Tag>}
                {s.reasons.length > 0 && <ReasonList reasons={s.reasons} />}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </div>

      <div className="tile">
        <h2>Verified findings ({verified.length})</h2>
        {verified.length === 0 ? <p className="muted">Nothing passed every gate. That is a valid outcome.</p> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Group</th><th>Metric</th><th>Direction</th><th>Difference vs the rest (CI)</th><th className="num">q</th><th className="num">n</th></tr></thead>
            <tbody>{verified.map((f, i) => (
              <tr key={i}>
                <td>{label(f.dimension)}: <strong>{f.group}</strong></td><td>{METRIC_LABEL[f.metric]}</td>
                <td>{f.direction}</td>
                <td>{formatDiffWithCi(f.diff, f.diff_ci_low, f.diff_ci_high, unitOf(f.metric), conf)}</td>
                <td className="num">{formatQ(f.q_value)}</td><td className="num">{f.n_group} / {f.n_rest}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <div className="tile nvcard">
        <button className="link" aria-expanded={showNV} onClick={() => setShowNV(!showNV)}>
          {showNV ? "▾" : "▸"} Not verified ({notVerified.length}) — not results, do not act on these
        </button>
        {showNV && (
          <ul className="nvlist">
            {notVerified.map((f, i) => <NotVerified key={i} f={f} />)}
          </ul>
        )}
      </div>

      <p className="muted small">Gates used: {gatesLine(report.gates)}</p>
      {report.notes.length > 0 && <ul className="plain muted small">{report.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </>
  );
}

function NotVerified({ f }: { f: EffectFinding }) {
  return (
    <li>
      <div>{label(f.dimension)}: {f.group} · {METRIC_LABEL[f.metric]} · n {f.n_group} / {f.n_rest}</div>
      {f.reasons.length === 0 ? <ul className="reasons"><li>No reason given.</li></ul> : <ReasonList reasons={f.reasons} />}
    </li>
  );
}

export function gatesLine(g: GateConfig): string {
  return [
    `${formatPct(g.confidence, 0)} confidence`, `FDR ${formatNum(g.fdr_alpha, 3)}`, `n ≥ ${g.min_n}`,
    `wins ≥ ${g.min_wins}`, `losses ≥ ${g.min_losses}`, `CI half-width ≤ ${g.max_ci_halfwidth_pts} pts or ≤ ${formatPct(g.max_ci_rel_halfwidth, 0)} relative`,
    `${g.bootstrap_resamples} resamples`, `seed ${g.random_seed}`,
  ].join(" · ");
}
