import { lazy, Suspense, useMemo, useState } from "react";
import { adminApi } from "./api";
import { dayUserSeries, formatEur, formatTokens, partialNote, type DayMetric } from "./m6format";
import type { UsageModel, UsageReport, UsageReportAll, UsageMetrics } from "../api.gen";
import { readPalette, useThemeVersion } from "../workbooks/chartTheme";
import { Empty, ErrorNote, Loading, useAction, useLoad } from "../ui";

// ECharts is large: it loads when this section first shows data.
const EChart = lazy(() => import("../workbooks/EChart"));


/** Admin page section: AI usage per person and model. `all` (superadmin) spans every workspace. */
export function Usage({ ws, superadmin }: { ws: string; superadmin: boolean }) {
  const [days, setDays] = useState(30);
  const [all, setAll] = useState(false);
  const [metric, setMetric] = useState<DayMetric>("cost");
  const u = useLoad<UsageReport | UsageReportAll>(() => (all ? adminApi.usageReportAll(days) : adminApi.usageReport(ws, days)), [all, ws, days]);
  const d = u.data;
  const theme = useThemeVersion();
  const pal = useMemo(() => readPalette(), [theme]);

  const dayOption = useMemo(() => {
    if (!d) return null;
    const s = dayUserSeries(d.by_day_user, metric);
    return {
      color: pal.series, backgroundColor: "transparent", textStyle: { fontFamily: pal.font, color: pal.ink }, animation: false,
      tooltip: { trigger: "axis" }, legend: { bottom: 0, textStyle: { color: pal.inkSoft } },
      grid: { left: 8, right: 8, top: 12, bottom: 40, containLabel: true },
      xAxis: { type: "category", data: s.days, axisLabel: { color: pal.inkSoft }, axisLine: { lineStyle: { color: pal.hairline } } },
      yAxis: { type: "value", axisLabel: { color: pal.inkSoft }, splitLine: { lineStyle: { color: pal.hairline } } },
      series: s.series.map((x) => ({ name: x.name, type: "bar", stack: "total", data: x.data })),
    };
  }, [d, metric, pal]);

  const userOption = useMemo(() => {
    if (!d) return null;
    const rows = [...d.by_user].sort((a, b) => (b.input_tokens + b.output_tokens) - (a.input_tokens + a.output_tokens));
    return {
      color: [pal.primary], backgroundColor: "transparent", textStyle: { fontFamily: pal.font, color: pal.ink }, animation: false,
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: "value", axisLabel: { color: pal.inkSoft }, splitLine: { lineStyle: { color: pal.hairline } } },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => r.name || "System"), axisLabel: { color: pal.inkSoft } },
      series: [{ name: "Tokens", type: "bar", data: rows.map((r) => r.input_tokens + r.output_tokens) }],
    };
  }, [d, pal]);

  const t: UsageMetrics | undefined = d?.totals;
  const partial = t ? partialNote(t.unpriced_calls) : null;

  return (
    <div className="card stack">
      <div className="row between">
        <h2>Usage</h2>
        <span className="row">
          {superadmin && (
            <select aria-label="Scope" value={all ? "all" : "ws"} onChange={(e) => setAll(e.target.value === "all")}>
              <option value="ws">This workspace</option><option value="all">All workspaces</option>
            </select>
          )}
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90].map((n) => <option key={n} value={n}>Last {n} days</option>)}
          </select>
        </span>
      </div>
      <ErrorNote error={u.error} />
      {u.loading && !d ? <Loading /> : d && (
        <>
          <div className="bento">
            <div className="tile w3"><span className="stat-sub">Calls</span><span className="stat">{(t?.calls ?? 0).toLocaleString()}</span></div>
            <div className="tile w3"><span className="stat-sub">Tokens</span><span className="stat">{formatTokens((t?.input_tokens ?? 0) + (t?.output_tokens ?? 0))}</span></div>
            <div className="tile w3"><span className="stat-sub">Estimated cost</span><span className="stat">{formatEur(t?.cost_eur)}</span>{partial && <span className="stat-sub">{partial}</span>}</div>
            <div className="tile w3"><span className="stat-sub">Average cost per call</span><span className="stat">{formatEur(t?.avg_cost_per_call_eur)}</span></div>
          </div>
          {d.by_day.length === 0 ? <Empty>No AI calls in this period.</Empty> : (
            <Suspense fallback={<p className="muted small">Loading chart…</p>}>
              <div className="row between">
                <h3>Per day, by person</h3>
                <select aria-label="Measure" value={metric} onChange={(e) => setMetric(e.target.value as DayMetric)}>
                  <option value="cost">Estimated cost</option><option value="tokens">Tokens</option>
                </select>
              </div>
              {dayOption && <EChart option={dayOption} label={`Daily ${metric === "cost" ? "cost" : "tokens"} stacked by person`} />}
              <h3>Tokens by person</h3>
              {userOption && <EChart option={userOption} label="Tokens by person" />}
            </Suspense>
          )}
          {"by_workspace" in d && (
            <>
              <h3>By workspace</h3>
              <div className="tablewrap"><table>
                <thead><tr><th>Workspace</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Cost</th></tr></thead>
                <tbody>{d.by_workspace.map((r) => (
                  <tr key={r.workspace_id ?? "none"}>
                    <td>{r.name ?? r.slug ?? "Unassigned"}</td><td className="num">{r.calls}</td>
                    <td className="num">{formatTokens(r.input_tokens + r.output_tokens)}</td>
                    <td className="num">{formatEur(r.cost_eur)}{r.unpriced_calls > 0 && <div className="muted small">{partialNote(r.unpriced_calls)}</div>}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </>
          )}
          <h3>By model</h3>
          <ModelTable report={d} editable={superadmin} onSaved={u.reload} />
        </>
      )}
    </div>
  );
}

function ModelTable({ report, editable, onSaved }: { report: UsageReport; editable: boolean; onSaved: () => void }) {
  if (report.by_model.length === 0) return <Empty>No AI calls in this period.</Empty>;
  return (
    <div className="tablewrap"><table>
      <thead><tr><th>Model</th><th className="num">Calls</th><th className="num">Tokens in</th><th className="num">Tokens out</th><th className="num">Cost</th><th className="num">Per call</th>{editable && <th>Price per 1M tokens (EUR)</th>}</tr></thead>
      <tbody>{report.by_model.map((m) => (
        <tr key={`${m.provider}/${m.model}`}>
          <td>{m.provider} {m.model}</td><td className="num">{m.calls}</td>
          <td className="num">{m.input_tokens.toLocaleString()}</td><td className="num">{m.output_tokens.toLocaleString()}</td>
          <td className="num">{formatEur(m.cost_eur)}{m.unpriced_calls > 0 && <div className="muted small">{partialNote(m.unpriced_calls)}</div>}</td><td className="num">{formatEur(m.avg_cost_per_call_eur)}</td>
          {editable && <td><PriceEditor m={m} onSaved={onSaved} /></td>}
        </tr>
      ))}</tbody>
    </table></div>
  );
}

function PriceEditor({ m, onSaved }: { m: UsageModel; onSaved: () => void }) {
  const [inp, setInp] = useState(m.input_per_mtok_eur != null ? String(m.input_per_mtok_eur) : "");
  const [out, setOut] = useState(m.output_per_mtok_eur != null ? String(m.output_per_mtok_eur) : "");
  const a = useAction();
  const ok = inp !== "" && out !== "" && Number(inp) >= 0 && Number(out) >= 0;
  return (
    <span className="row">
      <input type="number" step="any" min={0} aria-label={`Input price for ${m.model}`} placeholder="in" value={inp} onChange={(e) => setInp(e.target.value)} style={{ width: "5.5rem" }} />
      <input type="number" step="any" min={0} aria-label={`Output price for ${m.model}`} placeholder="out" value={out} onChange={(e) => setOut(e.target.value)} style={{ width: "5.5rem" }} />
      <button type="button" disabled={a.busy || !ok}
        onClick={() => void a.run(async () => { await adminApi.setPrice({ provider: m.provider as "gemini" | "anthropic", model: m.model, input_per_mtok_eur: Number(inp), output_per_mtok_eur: Number(out) }); onSaved(); })}>Save</button>
      <ErrorNote error={a.error} />
    </span>
  );
}
