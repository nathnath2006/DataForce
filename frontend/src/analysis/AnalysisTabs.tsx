import { NavLink } from "react-router";
import { useWs } from "../context";
import "./analysis.css";

const TABS = [
  { to: "analysis", label: "Flows", end: true },
  { to: "analysis/workbooks", label: "Workbooks", end: false },
  { to: "analysis/models", label: "Models", end: true },
  { to: "analysis/scan", label: "Insights", end: true },
];

/** The four Analysis tabs, shown at the top of every Analysis page. */
export function AnalysisTabs() {
  const { ws } = useWs();
  return (
    <nav className="an-tabs" aria-label="Analysis">
      {TABS.map((t) => (
        <NavLink key={t.to} to={`/w/${ws.slug}/${t.to}`} end={t.end}>{t.label}</NavLink>
      ))}
    </nav>
  );
}
