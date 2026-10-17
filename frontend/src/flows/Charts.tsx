import { asNum, niceScale, project, fmtCell } from "./pivot";
import type { ChartView } from "./types";

const W = 640, H = 300, M = { l: 56, r: 12, t: 12, b: 48 };
const PW = W - M.l - M.r, PH = H - M.t - M.b;

export function ChartSvg({ view }: { view: ChartView }) {
  const nonEmpty = view.series.some((s) => s.points.length > 0);
  if (!nonEmpty) return <p className="muted pad">No points to draw.</p>;
  const numericX = view.chart === "scatter" || view.series.every((s) => s.points.every((p) => asNum(p[0]) !== null));
  const cats: string[] = [];
  if (!numericX || view.chart === "bar") {
    for (const s of view.series) for (const p of s.points) { const k = fmtCell(p[0]); if (!cats.includes(k)) cats.push(k); }
  }
  const useCats = view.chart === "bar" || !numericX;
  const ys = view.series.flatMap((s) => s.points.map((p) => p[1]).filter((v): v is number => v !== null));
  const yMin = view.chart === "bar" ? Math.min(0, ...ys) : Math.min(...ys);
  const ysc = niceScale(yMin, Math.max(...ys, yMin));
  const xs = view.series.flatMap((s) => s.points.map((p) => asNum(p[0])).filter((v): v is number => v !== null));
  const xsc = !useCats ? niceScale(Math.min(...xs), Math.max(...xs)) : null;
  const px = (x: unknown): number => {
    if (useCats) { const i = cats.indexOf(fmtCell(x)); return M.l + ((i + 0.5) / cats.length) * PW; }
    return M.l + project(asNum(x) ?? 0, xsc as NonNullable<typeof xsc>, PW);
  };
  const py = (y: number) => M.t + PH - project(y, ysc, PH);
  const labelEvery = Math.max(1, Math.ceil(cats.length / 12));
  return (
    <div className="chartwrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${view.chart} chart of ${view.y_label} by ${view.x_label}`} className="chart">
        {ysc.ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={py(t)} y2={py(t)} className="grid" />
            <text x={M.l - 6} y={py(t) + 4} textAnchor="end" className="tick">{fmtCell(t)}</text>
          </g>
        ))}
        {useCats
          ? cats.map((c, i) => i % labelEvery === 0 && (
            <text key={c + i} x={px(c)} y={H - M.b + 16} textAnchor="middle" className="tick">{c.length > 14 ? c.slice(0, 13) + "…" : c}</text>))
          : xsc?.ticks.map((t) => <text key={t} x={M.l + project(t, xsc, PW)} y={H - M.b + 16} textAnchor="middle" className="tick">{fmtCell(t)}</text>)}
        <text x={M.l + PW / 2} y={H - 6} textAnchor="middle" className="axis">{view.x_label}</text>
        <text transform={`translate(12 ${M.t + PH / 2}) rotate(-90)`} textAnchor="middle" className="axis">{view.y_label}</text>
        <line x1={M.l} x2={M.l} y1={M.t} y2={M.t + PH} className="axisline" />
        <line x1={M.l} x2={W - M.r} y1={py(Math.max(0, ysc.min))} y2={py(Math.max(0, ysc.min))} className="axisline" />
        {view.series.map((s, si) => {
          const cls = `s${(si % 6) + 1}`;
          const pts = s.points.filter((p): p is [unknown, number] => p[1] !== null);
          if (view.chart === "bar") {
            const bw = Math.min(40, (PW / cats.length / view.series.length) * 0.8);
            const offset = (si - (view.series.length - 1) / 2) * bw;
            const base = py(Math.max(0, ysc.min));
            return <g key={si} className={cls}>{pts.map((p, i) => (
              <rect key={i} x={px(p[0]) + offset - bw / 2} width={bw} y={Math.min(py(p[1]), base)} height={Math.abs(base - py(p[1]))} className="bar">
                <title>{`${s.name} · ${fmtCell(p[0])}: ${fmtCell(p[1])}`}</title>
              </rect>))}</g>;
          }
          if (view.chart === "line") {
            const sorted = useCats ? pts : [...pts].sort((a, b) => (asNum(a[0]) ?? 0) - (asNum(b[0]) ?? 0));
            return <g key={si} className={cls}>
              <polyline fill="none" className="line" points={sorted.map((p) => `${px(p[0])},${py(p[1])}`).join(" ")} />
              {sorted.map((p, i) => <circle key={i} cx={px(p[0])} cy={py(p[1])} r={3} className="dot"><title>{`${s.name} · ${fmtCell(p[0])}: ${fmtCell(p[1])}`}</title></circle>)}
            </g>;
          }
          return <g key={si} className={cls}>{pts.map((p, i) => (
            <circle key={i} cx={px(p[0])} cy={py(p[1])} r={3} className="dot faint"><title>{`${fmtCell(p[0])}, ${fmtCell(p[1])}`}</title></circle>))}</g>;
        })}
      </svg>
      {view.series.length > 1 && (
        <div className="legend">{view.series.map((s, i) => <span key={i} className={`s${(i % 6) + 1}`}><i className="swatch" />{s.name}</span>)}</div>
      )}
      {view.truncated && <p className="muted small">Showing a capped number of points.</p>}
    </div>
  );
}
