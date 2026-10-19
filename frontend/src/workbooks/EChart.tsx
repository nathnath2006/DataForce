import { useEffect, useRef } from "react";
// Modular import: only the charts and components the workbook uses are bundled.
import * as echarts from "echarts/core";
import { BarChart, FunnelChart, HeatmapChart, LineChart, PieChart, ScatterChart, TreemapChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ChartEvent, Option } from "./option";

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, TreemapChart, FunnelChart,
  GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CanvasRenderer,
]);

export function EChart(props: { option: Option; label: string; onPick?: (ev: ChartEvent) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const pick = useRef(props.onPick);
  pick.current = props.onPick;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const c = echarts.init(el, undefined, { renderer: "canvas" });
    chart.current = c;
    c.on("click", (p) => pick.current?.(p as unknown as ChartEvent));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el);
    return () => { ro.disconnect(); c.dispose(); chart.current = null; };
  }, []);

  useEffect(() => { chart.current?.setOption(props.option as echarts.EChartsCoreOption, true); }, [props.option]);

  return <div ref={host} className="wb-chart" role="img" aria-label={props.label} />;
}

export default EChart;
