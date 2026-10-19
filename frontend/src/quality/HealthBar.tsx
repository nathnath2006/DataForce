import type { QualitySegment } from "./api";
import "./quality.css";

/** Whole-percent widths by the largest-remainder method: they sum to 100 when total > 0, else all 0. */
export function segmentWidths(counts: number[]): number[] {
  const safe = counts.map((c) => (Number.isFinite(c) && c > 0 ? c : 0));
  const total = safe.reduce((a, b) => a + b, 0);
  if (total === 0) return safe.map(() => 0);
  const raw = safe.map((c) => (c / total) * 100);
  const out = raw.map(Math.floor);
  let left = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw.map((r, i) => ({ i, f: r - Math.floor(r) })).sort((a, b) => b.f - a.f || a.i - b.i);
  for (const { i } of order) {
    if (left <= 0) break;
    if ((safe[i] ?? 0) > 0) { out[i] = (out[i] ?? 0) + 1; left -= 1; }
  }
  return out;
}

export function HealthBar(props: { label: string; total: number; segments: QualitySegment[] }) {
  const { label, total, segments } = props;
  const good = segments.filter((s) => s.kind === "ok").reduce((a, s) => a + s.count, 0);
  const widths = segmentWidths(segments.map((s) => s.count));
  const aria = `${label}: ${good} of ${total}. ` + segments.map((s) => `${s.label} ${s.count}`).join(", ");
  return (
    <div className="hbar">
      <div className="hbar-head">
        <span className="hbar-label">{label}</span>
        <span className="hbar-n">{good} of {total}</span>
      </div>
      <div className="hbar-track" role="img" aria-label={aria}>
        {segments.map((s, i) => (widths[i] ?? 0) > 0 && (
          <span key={s.kind} className={`hbar-seg ${s.kind}`} style={{ width: `${widths[i]}%` }} />
        ))}
      </div>
      <ul className="hbar-key">
        {segments.map((s) => (
          <li key={s.kind}><span className={`hbar-dot ${s.kind}`} aria-hidden="true" />{s.label}: <strong>{s.count}</strong></li>
        ))}
      </ul>
    </div>
  );
}
