import { meaningOf, pct, sparkBars } from "./columns";
import type { ColumnProfile } from "./types";

const W = 64;
const H = 20;

function Spark({ p }: { p: ColumnProfile }) {
  const values = p.hist ? p.hist.counts : p.top ? p.top.map((t) => t.count) : [];
  if (values.length === 0) return <span className="muted small">-</span>;
  const label = p.hist
    ? `Distribution from ${p.hist.min} to ${p.hist.max}`
    : `Most frequent values: ${(p.top ?? []).map((t) => `${t.value} (${t.count})`).join(", ")}`;
  return (
    <svg className="cg-spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      <title>{label}</title>
      {sparkBars(values, W, H).map((b, i) => <rect key={i} x={b.x} y={b.y} width={b.w} height={b.h} />)}
    </svg>
  );
}

export function ColumnsGrid({ profile, nRows }: { profile: ColumnProfile[] | null | undefined; nRows: number | null }) {
  if (!profile || profile.length === 0) return <p className="muted pad">No column profile for this result. Run the flow again.</p>;
  return (
    <div className="cg-wrap">
      <table className="cg">
        <thead>
          <tr><th>Column</th><th>Type</th><th>Distribution</th><th>Filled</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          {profile.map((p) => {
            const q = pct(p.non_null, p.n);
            const m = meaningOf(p);
            return (
              <tr key={p.name}>
                <td className="cg-name" title={p.name}>{p.name}</td>
                <td><span className="cg-type">{p.dtype}</span></td>
                <td><Spark p={p} /></td>
                <td>
                  <span className="cg-q" role="img" aria-label={`${q}% filled, ${p.non_null} of ${p.n}`}>
                    <span className="cg-qbar"><span className="cg-qfill" style={{ width: `${q}%` }} /></span>
                    <span className="cg-qpct">{q}%</span>
                  </span>
                </td>
                <td>
                  <span className="cg-chip" title="A guess from the column name and type, not a verified fact">{m}</span>
                  {p.n_unique_capped && <span className="muted small" title="Distinct values counted up to 10,000"> 10,000+ distinct</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {nRows != null && <p className="muted small">Counts cover all {nRows.toLocaleString("en-US")} rows; at most 60 columns are profiled.</p>}
    </div>
  );
}
