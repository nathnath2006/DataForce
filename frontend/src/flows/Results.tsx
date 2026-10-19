import { useMemo, useState } from "react";
import { formatNum, formatPct, formatPts, formatQ } from "../lib";
import { ErrorNote, Tag, useAction } from "../ui";
import { modelApi } from "../models/api";
import { ColumnsGrid } from "./ColumnsGrid";
import { ChartSvg } from "./Charts";
import { fmtCell, isTotalColumn, pivotModel } from "./pivot";
import type {
  ClusterView, EngagementView, MetricOut, ModelView, NodeResult, PivotView, ScoreView, StatsRow, StatsView,
  TouchpointView, VelocityView,
} from "./types";

/** Where a model block of the open flow can be saved from: the server re-runs the SAVED flow. */
export interface SaveTarget { slug: string; flowId: string; nodeId: string; dirty: boolean }

export function ResultsPanel({ result, title, save }: { result: NodeResult | undefined; title: string; save?: SaveTarget }) {
  const [tab, setTab] = useState<"view" | "table" | "columns">("view");
  if (!result) return <p className="muted pad">Run the flow to see the result of {title}.</p>;
  const v = result.view;
  const showView = v !== null && tab === "view";
  const hasTable = result.status === "ok" && result.columns.length > 0;
  return (
    <div className="results">
      <div className="row between wrap">
        <strong>{title}</strong>
        <span className="muted small">
          {result.n_rows != null && `${result.n_rows.toLocaleString("en-US")} rows · `}{result.elapsed_ms} ms
        </span>
        {hasTable && (
          <span className="row">
            {v && <button className={tab === "view" ? "primary" : ""} onClick={() => setTab("view")}>Result</button>}
            <button className={tab === "table" || (!v && tab === "view") ? "primary" : ""} onClick={() => setTab("table")}>Table</button>
            <button className={tab === "columns" ? "primary" : ""} onClick={() => setTab("columns")}>Columns</button>
          </span>
        )}
      </div>
      {result.status === "error" && <div className="note err" role="alert">{result.error ?? "This block failed."}</div>}
      {result.status === "skipped" && <div className="note warn">Skipped: an upstream block failed.</div>}
      {result.warnings.map((w, i) => <div className="note warn" key={i}>{w}</div>)}
      {save && <SaveModel key={save.nodeId} result={result} save={save} />}
      {result.status === "ok" && (tab === "columns" ? <ColumnsGrid profile={result.profile} nRows={result.n_rows} /> : showView && v ? <ViewSwitch view={v} /> : <PreviewTable result={result} />)}
    </div>
  );
}

function ViewSwitch({ view }: { view: NonNullable<NodeResult["view"]> }) {
  switch (view.kind) {
    case "pivot": return <PivotTable view={view} />;
    case "chart": return <ChartSvg view={view} />;
    case "stats": return <StatsPanel view={view} />;
    case "model": return <ModelPanel view={view} />;
    case "cluster": return <ClusterPanel view={view} />;
    case "score": return <ScorePanel view={view} />;
    case "velocity": return <VelocityPanel view={view} />;
    case "engagement": return <EngagementPanel view={view} />;
    case "touchpoint": return <TouchpointPanel view={view} />;
  }
}

/** Shown only for a successful model or cluster block whose parameters can be exported. */
function SaveModel({ result, save }: { result: NodeResult; save: SaveTarget }) {
  const [name, setName] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const act = useAction();
  const kind = result.view?.kind;
  if (result.status !== "ok" || (kind !== "model" && kind !== "cluster") || !result.model_params) return null;
  if (result.model_params.exportable === false) {
    return <div className="note warn">This RBF model has too many support vectors to be saved. Use a linear kernel or fewer training rows.</div>;
  }
  if (save.dirty) return <p className="muted small">Save the flow to keep this model: the server re-runs the saved flow.</p>;
  const go = async () => {
    const m = await act.run(() => modelApi.save(save.slug, { flow_id: save.flowId, node_id: save.nodeId, name: name.trim() }));
    if (m) { setDone(`Saved as "${m.name}" (${m.status.replace("_", " ")}). Find it in Analysis, Models.`); setName(""); }
  };
  // An RBF model keeps its support vectors: training rows (standardised numbers), up to 2,000.
  const keepsRows = result.model_params.kernel === "rbf" && Array.isArray(result.model_params.support_vectors);
  return (
    <div className="stack">
      <div className="row wrap">
        <input aria-label="Model name" placeholder="Model name" maxLength={200} value={name} onChange={(ev) => { setName(ev.target.value); setDone(null); }} />
        <button className="primary" disabled={!name.trim() || act.busy} onClick={go}>Save model</button>
        {done && <span className="muted small">{done}</span>}
        {act.error && <ErrorNote error={act.error} />}
      </div>
      {keepsRows && <p className="muted small">This RBF model stores {String((result.model_params.support_vectors as unknown[]).length)} training rows (as standardised numbers) to score new rows. A linear kernel stores none. Deleting the model removes them.</p>}
    </div>
  );
}

export function StatusTag({ status }: { status: "verified" | "not_verified" | "exploratory" }) {
  return status === "verified" ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">{status === "exploratory" ? "exploratory" : "not verified"}</Tag>;
}

function ScorePanel({ view }: { view: ScoreView }) {
  return (
    <div className={`stack${view.status === "verified" ? "" : " nvbox"}`}>
      <div className="row wrap">
        <StatusTag status={view.status} />
        <span className="muted small">{view.model_name} ({view.model_kind}) · {view.n_scored} of {view.n_rows} rows scored · scores take the model's status</span>
      </div>
      {view.notes.map((n, i) => <div className="note warn" key={i}>{n}</div>)}
    </div>
  );
}

function VelocityPanel({ view }: { view: VelocityView }) {
  return (
    <div className="stack">
      <p className="muted small">{view.benchmark_note}</p>
      <p className="muted small">Fast track at index {formatNum(view.fast_track_at, 2)} or more · stagnant below {formatNum(view.stagnant_below, 2)} · {Object.entries(view.counts).map(([k, n]) => `${k.replace("_", " ")} ${n}`).join(" · ")}</p>
      <div className="tablewrap"><table>
        <thead><tr><th>Stage</th><th className="num">Median days</th><th className="num">Deals</th></tr></thead>
        <tbody>{view.benchmarks.map((b) => <tr key={b.stage}><td>{b.stage}</td><td className="num">{formatNum(b.median_days, 1)}</td><td className="num">{b.n}</td></tr>)}</tbody>
      </table></div>
    </div>
  );
}

function EngagementPanel({ view }: { view: EngagementView }) {
  return (
    <div className="stack">
      <p className="muted small">{view.formula}. Run date {view.today}.</p>
      <p className="muted small">Weights: {Object.entries(view.weights).map(([k, w]) => `${k} ${w}`).join(", ")} · {view.n_accounts} accounts · {view.n_penalised} penalised</p>
    </div>
  );
}

function TouchpointPanel({ view }: { view: TouchpointView }) {
  return (
    <div className="stack">
      <p className="muted small">{view.formula}</p>
      <p className="muted small">{view.n_groups} groups · {view.n_no_outreach} without outreach (empty ratio)</p>
    </div>
  );
}

function PreviewTable({ result }: { result: NodeResult }) {
  const cols = result.columns.length ? result.columns.map((c) => c.name) : Object.keys(result.preview[0] ?? {});
  if (cols.length === 0) return <p className="muted pad">No table output.</p>;
  const numeric = new Set(result.columns.filter((c) => c.dtype === "number" || c.dtype === "integer").map((c) => c.name));
  return (
    <div>
      <div className="tablewrap preview"><table>
        <thead><tr>{cols.map((c) => <th key={c} className={numeric.has(c) ? "num" : ""}>{c}</th>)}</tr></thead>
        <tbody>{result.preview.map((r, i) => (
          <tr key={i}>{cols.map((c) => (
            <td key={c} className={`cell${numeric.has(c) ? " num" : ""}`} title={fmtCell(r[c])}>{fmtCell(r[c])}</td>
          ))}</tr>
        ))}</tbody>
      </table></div>
      {result.n_rows != null && result.n_rows > result.preview.length && (
        <p className="muted small">Showing the first {result.preview.length} of {result.n_rows.toLocaleString("en-US")} rows.</p>
      )}
    </div>
  );
}

export function PivotTable({ view }: { view: PivotView }) {
  const m = useMemo(() => pivotModel(view), [view]);
  return (
    <div>
      <div className="tablewrap preview"><table className="pivot">
        <thead><tr>
          {m.headers.map((h) => <th key={h} className="sticky-col">{h}</th>)}
          {m.columns.map((c, i) => <th key={i} className={`num${isTotalColumn(m, i) ? " total" : ""}`}>{c}</th>)}
        </tr></thead>
        <tbody>{m.rows.map((r, i) => (
          <tr key={i} className={r.isTotal ? "total" : ""}>
            {r.keys.map((k, j) => <th key={j} scope="row" className="sticky-col">{k}</th>)}
            {r.cells.map((c, j) => <td key={j} className={`num${isTotalColumn(m, j) ? " total" : ""}`}>{c}</td>)}
          </tr>
        ))}</tbody>
      </table></div>
      {m.truncatedColumns > 0 && <p className="muted small">{m.truncatedColumns} less frequent column values are not shown.</p>}
    </div>
  );
}

const fmtVal = (kind: "rate" | "median", v: number | null) => (kind === "rate" ? formatPct(v) : formatNum(v, 2));
const fmtDiff = (kind: "rate" | "median", v: number | null) =>
  kind === "rate" ? formatPts(v) : v == null ? "—" : `${v > 0 ? "+" : ""}${formatNum(v, 2)}`;

function StatsPanel({ view }: { view: StatsView }) {
  const [showNV, setShowNV] = useState(false);
  const verified = view.rows.filter((r) => r.status === "verified");
  const nv = view.rows.filter((r) => r.status !== "verified");
  const k = view.outcome_kind;
  return (
    <div className="stack">
      <p className="muted small">Outcome <strong>{view.outcome}</strong> ({k}) · {view.method} · {view.excluded_missing} rows excluded for missing values</p>
      <div className="tablewrap"><table>
        <thead><tr><th>Group</th><th className="num">n</th><th>Value (CI)</th><th>Rest</th><th>Difference (CI)</th><th className="num">p</th><th className="num">q</th><th>Status</th></tr></thead>
        <tbody>
          <StatsLine r={view.overall} kind={k} overall />
          {verified.map((r) => <StatsLine key={r.group} r={r} kind={k} />)}
        </tbody>
      </table></div>
      {verified.length === 0 && <p className="muted">Nothing passed every gate. That is a valid outcome.</p>}
      <div className="card nvcard">
        <button className="link" aria-expanded={showNV} onClick={() => setShowNV(!showNV)}>
          {showNV ? "▾" : "▸"} Not verified ({nv.length}): not results, do not act on these
        </button>
        {showNV && (
          <div className="tablewrap"><table>
            <tbody>{nv.map((r) => <StatsLine key={r.group} r={r} kind={k} />)}</tbody>
          </table></div>
        )}
      </div>
    </div>
  );
}

function StatsLine({ r, kind, overall }: { r: StatsRow; kind: "rate" | "median"; overall?: boolean }) {
  const ci = (lo: number | null, hi: number | null, f: (v: number | null) => string) => (lo == null || hi == null ? "" : ` (${f(lo)} to ${f(hi)})`);
  const verified = r.status === "verified";
  return (
    <>
      <tr className={verified || overall ? "" : "nv"}>
        <td>{overall ? "(all)" : r.group}</td>
        <td className="num">{r.n}</td>
        <td>{fmtVal(kind, r.value)}{ci(r.ci_low, r.ci_high, (v) => fmtVal(kind, v))}</td>
        <td>{overall ? "" : fmtVal(kind, r.rest_value)}</td>
        <td>{overall ? "" : `${fmtDiff(kind, r.diff)}${ci(r.diff_ci_low, r.diff_ci_high, (v) => fmtDiff(kind, v))}`}</td>
        <td className="num">{overall ? "" : formatQ(r.p_value)}</td>
        <td className="num">{overall ? "" : formatQ(r.q_value)}</td>
        <td>{overall ? "" : verified ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">not verified</Tag>}</td>
      </tr>
      {!verified && !overall && r.reasons.length > 0 && (
        <tr className="nv"><td colSpan={8}><ul className="reasons">{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul></td></tr>
      )}
    </>
  );
}

const PCT_METRICS = new Set(["accuracy"]);
function metricText(m: MetricOut, v: number | null | undefined): string {
  return PCT_METRICS.has(m.name) ? formatPct(v ?? null) : formatNum(v ?? null, 3);
}

function MetricsTable({ metrics }: { metrics: MetricOut[] }) {
  return (
    <div className="tablewrap"><table>
      <thead><tr><th>Metric</th><th className="num">Value</th><th>95% CI</th><th className="num">Baseline</th></tr></thead>
      <tbody>{metrics.map((m) => (
        <tr key={m.name}>
          <td>{m.name}</td><td className="num">{metricText(m, m.value)}</td>
          <td>{m.ci_low != null && m.ci_high != null ? `${metricText(m, m.ci_low)} to ${metricText(m, m.ci_high)}` : ""}</td>
          <td className="num">{m.baseline != null ? metricText(m, m.baseline) : ""}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

function ModelPanel({ view }: { view: ModelView }) {
  const ok = view.status === "verified";
  const coefs = [...view.coefficients].sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef));
  return (
    <div className={`stack${ok ? "" : " nvbox"}`}>
      <div className="row wrap">
        {ok ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">not verified</Tag>}
        <span className="muted small">{view.model.replace("_", " ")} · train {view.n_train} · test {view.n_test} · {view.dropped_missing} rows dropped for missing values</span>
      </div>
      {!ok && (
        <div className="note warn">
          Not verified: do not act on this model.
          <ul className="reasons">{view.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      )}
      <MetricsTable metrics={view.metrics} />
      {view.confusion && (
        <div>
          <strong>Confusion matrix (test)</strong>
          <table className="confusion"><thead><tr><th /><th>Predicted no</th><th>Predicted yes</th></tr></thead>
            <tbody>
              <tr><th scope="row">Actual no</th><td className="num">{view.confusion[0]?.[0]}</td><td className="num">{view.confusion[0]?.[1]}</td></tr>
              <tr><th scope="row">Actual yes</th><td className="num">{view.confusion[1]?.[0]}</td><td className="num">{view.confusion[1]?.[1]}</td></tr>
            </tbody></table>
        </div>
      )}
      {coefs.length === 0 && <p className="muted small">This kernel has no coefficients; the model is described by its support vectors.</p>}
      {coefs.length > 0 && <div>
        <strong>Coefficients</strong> <span className="muted small">(associations, not causes)</span>
        <div className="tablewrap"><table>
          <tbody>{coefs.map((c) => <tr key={c.feature}><td>{c.feature}</td><td className="num">{formatNum(c.coef, 4)}</td></tr>)}</tbody>
        </table></div>
      </div>}
    </div>
  );
}

function ClusterPanel({ view }: { view: ClusterView }) {
  const feats = Object.keys(view.centroids[0] ?? {});
  const total = view.sizes.reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="stack">
      <div className="row wrap"><Tag kind="mute">exploratory</Tag>
        <span className="muted small">k = {view.k} · clusters describe the data, they do not prove anything · {view.dropped_missing} rows dropped for missing values</span></div>
      <div className="tablewrap"><table>
        <thead><tr><th>Cluster</th><th className="num">Size</th><th className="num">Share</th>{feats.map((f) => <th key={f} className="num">{f}</th>)}</tr></thead>
        <tbody>{view.sizes.map((s, i) => (
          <tr key={i}><td>{i}</td><td className="num">{s}</td><td className="num">{formatPct(s / total, 0)}</td>
            {feats.map((f) => <td key={f} className="num">{fmtCell(view.centroids[i]?.[f])}</td>)}</tr>
        ))}</tbody>
      </table></div>
      <MetricsTable metrics={view.metrics} />
    </div>
  );
}
