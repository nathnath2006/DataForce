import { useState } from "react";
import { formatNum } from "../lib";
import { ErrorNote, Tag, useAction } from "../ui";
import { SourcePicker, sourceReady } from "../workbooks/SourcePicker";
import type { Source } from "../workbooks/types";
import { modelApi, type SavedModel, type ScoreResult } from "./api";

const cell = (v: unknown): string => (v === null || v === undefined ? "" : typeof v === "number" ? formatNum(v, 4) : String(v));

/** Score a CRM table or a flow block with a saved model. Scores carry the model's status. */
export function ScoreNow({ slug, model }: { slug: string; model: SavedModel }) {
  const [source, setSource] = useState<Source>({ kind: "crm", table: "deals" });
  const [res, setRes] = useState<ScoreResult | null>(null);
  const act = useAction();
  const go = async () => {
    setRes(null);
    const r = await act.run(() => modelApi.score(slug, model.id, source));
    if (r) setRes(r);
  };
  return (
    <div className="stack md-score">
      <SourcePicker value={source} onChange={(s) => { setSource(s); setRes(null); }} />
      <div className="row">
        <button className="primary" disabled={!sourceReady(source) || act.busy} onClick={go}>{act.busy ? "Scoring…" : "Score now"}</button>
      </div>
      <ErrorNote error={act.error} />
      {res && <ScoreResultView res={res} />}
    </div>
  );
}

function ScoreResultView({ res }: { res: ScoreResult }) {
  const s = res.summary;
  const ok = res.status === "verified";
  return (
    <div className={`stack${ok ? "" : " nvbox"}`}>
      <div className="row wrap">
        {ok ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">{res.status === "exploratory" ? "exploratory" : "not verified"}</Tag>}
        <span className="muted small">{res.n_scored.toLocaleString("en-US")} of {res.n_rows.toLocaleString("en-US")} rows scored</span>
      </div>
      {res.status_note && <div className="note warn">{res.status_note}</div>}
      {res.notes.map((n, i) => <div className="note warn" key={i}>{n}</div>)}
      <p className="small">
        {s.mean != null && <>mean {formatNum(s.mean, 3)} · min {formatNum(s.min ?? null, 3)} · max {formatNum(s.max ?? null, 3)}</>}
        {s.class_counts && <>{s.mean != null ? " · " : ""}{Object.entries(s.class_counts).map(([k, n]) => `${k}: ${n}`).join(" · ")}</>}
      </p>
      <div className="tablewrap preview"><table>
        <thead><tr>{res.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{res.rows.map((r, i) => <tr key={i}>{res.columns.map((c) => <td key={c} className="cell">{cell(r[c])}</td>)}</tr>)}</tbody>
      </table></div>
      {res.n_rows > res.rows.length && <p className="muted small">Showing the first {res.rows.length} rows.</p>}
    </div>
  );
}
