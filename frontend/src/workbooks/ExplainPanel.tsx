import { useEffect, useMemo, useState } from "react";
import { formatNum, formatPct, formatPts, formatQ } from "../lib";
import { ErrorNote, Tag, useAction } from "../ui";
import { wbApi } from "./api";
import { isNumeric } from "./spec";
import type { ColumnInfo, ExplainFinding, ExplainResponse, Filter, Source } from "./types";

interface MeasureOpt { key: string; label: string; column: string; kind: "rate" | "median" }

export function measureOptions(cols: ColumnInfo[]): MeasureOpt[] {
  const out: MeasureOpt[] = [];
  for (const c of cols) if (c.dtype === "boolean") out.push({ key: `rate:${c.name}`, label: `Rate of ${c.name} = true`, column: c.name, kind: "rate" });
  for (const c of cols) if (isNumeric(c.dtype)) out.push({ key: `median:${c.name}`, label: `Median of ${c.name}`, column: c.name, kind: "median" });
  return out;
}

export function ExplainPanel(props: {
  ws: string; source: Source; fields: ColumnInfo[]; filters: Filter[]; preferred: string[]; onClose: () => void;
}) {
  const opts = useMemo(() => measureOptions(props.fields), [props.fields]);
  const attrCols = useMemo(() => props.fields.filter((c) => c.dtype === "text" || c.dtype === "boolean"), [props.fields]);
  const [measure, setMeasure] = useState("");
  const [attrs, setAttrs] = useState<string[]>([]);
  const [res, setRes] = useState<ExplainResponse | null>(null);
  const act = useAction();
  useEffect(() => {
    setRes(null);
    setMeasure(opts.find((o) => o.column === "is_won")?.key ?? opts[0]?.key ?? "");
    const pref = props.preferred.filter((p) => attrCols.some((c) => c.name === p));
    setAttrs((pref.length ? pref : attrCols.filter((c) => c.name !== "is_won").map((c) => c.name)).slice(0, 5));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts, attrCols]);
  const m = opts.find((o) => o.key === measure);
  const toggle = (n: string) => setAttrs((a) => (a.includes(n) ? a.filter((x) => x !== n) : a.length >= 5 ? a : [...a, n]));
  const run = () => act.run(async () => {
    if (!m) return;
    setRes(await wbApi.explain(props.ws, {
      source: props.source,
      measure: { column: m.column, kind: m.kind, ...(m.kind === "rate" ? { success_value: true } : {}) },
      attributes: attrs.filter((a) => a !== m.column), filters: props.filters,
    }));
  });
  const rate = res?.measure.kind === "rate";
  const fmt = (v: number | null) => (rate ? formatPct(v) : formatNum(v, 2));
  const fmtDiff = (v: number | null) => (rate ? formatPts(v) : v === null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${formatNum(Math.abs(v), 2)}`);
  const card = (f: ExplainFinding) => (
    <li key={`${f.attribute}:${f.group}`} className={`wb-finding ${f.status}`}>
      <div className="row between wrap">
        <strong>{f.attribute} = {f.group}</strong>
        <Tag kind={f.status === "verified" ? "ok" : "mute"}>{f.status === "verified" ? "verified" : "not verified"}</Tag>
      </div>
      <div className="small">
        {fmt(f.value)} vs {fmt(f.rest_value)} for the rest ({fmtDiff(f.diff)}
        {f.diff_ci_low !== null && f.diff_ci_high !== null && `, CI ${fmtDiff(f.diff_ci_low)} to ${fmtDiff(f.diff_ci_high)}`}) · n = {f.n} · q = {formatQ(f.q_value)}
      </div>
      {f.reasons.length > 0 && <ul className="small muted wb-reasons">{f.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
    </li>
  );
  return (
    <aside className="card wb-side" aria-label="Explain">
      <div className="row between"><h3>Explain</h3><button className="ghost" aria-label="Close Explain" onClick={props.onClose}>×</button></div>
      <p className="muted small">Each group against the rest, with the same gates and false-discovery control as Insights; that control runs within each attribute, not across them. The canvas filters apply.</p>
      <label>Measure
        <select value={measure} onChange={(e) => { setMeasure(e.target.value); setRes(null); }}>
          {opts.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
      </label>
      <fieldset className="wb-attrs"><legend>Attributes (up to 5)</legend>
        {attrCols.filter((c) => c.name !== m?.column).map((c) => (
          <label key={c.name} className="row"><input type="checkbox" checked={attrs.includes(c.name)} onChange={() => toggle(c.name)} /> {c.name}</label>
        ))}
      </fieldset>
      <button className="primary" disabled={!m || attrs.length === 0 || act.busy} onClick={() => void run()}>{act.busy ? "Running…" : "Explain"}</button>
      <ErrorNote error={act.error} />
      {res && (
        <div className="stack">
          <p className="small">{res.n_rows.toLocaleString("en-US")} rows · {res.method}</p>
          {res.truncated_source && <p className="note warn small">Computed on the first {res.n_rows.toLocaleString("en-US")} rows (the source is capped).</p>}
          <h4>Verified ({res.verified.length})</h4>
          {res.verified.length === 0 && <p className="muted small">Nothing could be verified with this data.</p>}
          <ul className="plain">{res.verified.map(card)}</ul>
          <details>
            <summary>Not verified ({res.not_verified.length})</summary>
            <p className="muted small">Not verified does not mean no effect: it means the data cannot establish it.</p>
            <ul className="plain">{res.not_verified.map(card)}</ul>
          </details>
          {res.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
        </div>
      )}
    </aside>
  );
}
