import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { ErrorNote, toApiError } from "../ui";
import { wbApi } from "./api";
import { readPalette, useThemeVersion } from "./chartTheme";
import { buildOption, buildPivot, exact, kpiOf, labelOf, pickFromEvent, type ChartEvent, type Pick } from "./option";
import { buildQuery, displayTitle, dimensionsOf, VIZ_LABEL, missingSlots } from "./spec";
import type { Filter, QueryResponse, Visualization } from "./types";

const EChart = lazy(() => import("./EChart"));

export function useViz(ws: string, viz: Visualization, filters: Filter[]) {
  const req = useMemo(() => buildQuery(viz, filters), [viz, filters]);
  const key = JSON.stringify(req);
  const [state, setState] = useState<{ data: QueryResponse | null; error: unknown; loading: boolean }>(
    { data: null, error: null, loading: false },
  );
  useEffect(() => {
    if (!req) { setState({ data: null, error: null, loading: false }); return; }
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    wbApi.query(ws, req).then(
      (data) => { if (live) setState({ data, error: null, loading: false }); },
      (e: unknown) => { if (live) setState({ data: null, error: toApiError(e), loading: false }); },
    );
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws, key]);
  return state;
}

/** One visualization: runs its query (canvas + cross filters included) and draws the result. */
export function VizTile(props: {
  ws: string; viz: Visualization; filters: Filter[]; selected: boolean; picked: string | null;
  onPick: (p: Pick) => void;
}) {
  const { viz } = props;
  const { data, error, loading } = useViz(props.ws, viz, props.filters);
  const theme = useThemeVersion();
  const missing = missingSlots(viz);
  const option = useMemo(
    () => (data ? buildOption(viz, data, readPalette()) : null),
    // theme: rebuild with the new token values after a light/dark switch
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [viz, data, theme],
  );
  const pick = (ev: ChartEvent) => { if (data) { const p = pickFromEvent(viz, data, ev); if (p) props.onPick(p); } };
  const clickable = viz.type !== "kpi" && dimensionsOf(viz).length > 0;
  return (
    <div className="wb-tile-body">
      {missing.length > 0 && <p className="muted small wb-empty">Add: {missing.join(", ")}</p>}
      <ErrorNote error={error} />
      {loading && !data && <p className="muted small">Loading…</p>}
      {data && (
        <>
          {data.truncated_source && (
            <p className="note warn small">Computed on the first {data.n_source_rows.toLocaleString("en-US")} rows (the source is capped).</p>
          )}
          {data.rows.length === 0 && <p className="muted wb-empty">No rows match the filters.</p>}
          {data.rows.length > 0 && option && (
            <Suspense fallback={<p className="muted small">Loading chart…</p>}>
              <EChart option={option} label={`${VIZ_LABEL[viz.type]} chart: ${displayTitle(viz)}`} onPick={clickable ? pick : undefined} />
            </Suspense>
          )}
          {data.rows.length > 0 && viz.type === "kpi" && <Kpi viz={viz} data={data} />}
          {data.rows.length > 0 && viz.type === "table" && <DataTable data={data} onPick={clickable ? props.onPick : undefined} viz={viz} picked={props.picked} />}
          {data.rows.length > 0 && viz.type === "pivot" && <PivotTable viz={viz} data={data} />}
          {data.notes.filter((n) => !n.startsWith("computed on")).map((n) => <p key={n} className="muted small">{n}</p>)}
        </>
      )}
    </div>
  );
}

function Kpi({ viz, data }: { viz: Visualization; data: QueryResponse }) {
  const k = kpiOf(viz, data);
  return <div className="wb-kpi"><b>{k.value}</b><span>{k.label}</span></div>;
}

function DataTable(props: { viz: Visualization; data: QueryResponse; picked: string | null; onPick?: (p: Pick) => void }) {
  const { data, viz } = props;
  const dims = new Set(dimensionsOf(viz));
  return (
    <div className="tablewrap wb-table"><table>
      <thead><tr>{data.columns.map((c) => <th key={c.name} className={dims.has(c.name) ? "" : "num"}>{c.name}</th>)}</tr></thead>
      <tbody>{data.rows.map((r, i) => (
        <tr key={i}>{r.map((v, j) => {
          const col = data.columns[j]!;
          const isDim = dims.has(col.name);
          if (isDim && props.onPick && j === 0) {
            const raw = (v ?? null) as Pick["value"];
            return (
              <td key={j}><button className={`link ${props.picked === labelOf(v) ? "on" : ""}`}
                onClick={() => props.onPick?.({ column: col.name, value: raw, label: labelOf(v) })}>{labelOf(v)}</button></td>
            );
          }
          return <td key={j} className={isDim ? "" : "num"}>{isDim ? labelOf(v) : exact(v)}</td>;
        })}</tr>
      ))}</tbody>
    </table></div>
  );
}

function PivotTable({ viz, data }: { viz: Visualization; data: QueryResponse }) {
  const p = buildPivot(viz, data);
  const multi = p.measures.length > 1;
  return (
    <div className="tablewrap wb-table"><table className="pivot">
      <thead>
        <tr>
          <th colSpan={Math.max(1, p.rowHeads.length)}>{p.rowHeads.join(" / ")}</th>
          {p.colKeys.map((k, c) => <th key={c} className="num" colSpan={p.measures.length}>{k.join(" / ") || (multi ? "" : p.measures[0])}</th>)}
        </tr>
        {multi && <tr><th colSpan={Math.max(1, p.rowHeads.length)} />{p.colKeys.flatMap((_, c) => p.measures.map((m) => <th key={`${c}${m}`} className="num">{m}</th>))}</tr>}
      </thead>
      <tbody>{p.rowKeys.map((rk, r) => (
        <tr key={r}>
          {rk.map((x, i) => <th key={i} className="sticky-col">{x}</th>)}
          {p.colKeys.flatMap((_, c) => p.measures.map((m, mi) => <td key={`${c}${m}`} className="num">{exact(p.cell(r, c, mi))}</td>))}
        </tr>
      ))}</tbody>
    </table></div>
  );
}
