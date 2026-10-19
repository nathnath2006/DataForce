import type { ReactNode } from "react";
import type { DealOut } from "../types";
import { label } from "../lib";
import { roadmapSteps } from "./logic";
import "./shell.css";

export function StageRoadmap({ deal }: { deal: DealOut }) {
  const steps = roadmapSteps(deal.stage);
  return (
    <div className="roadmap-wrap">
      <ol className="roadmap" aria-label={`Stage of ${deal.name}: ${label(deal.stage)}`}>
        {steps.map((s) => (
          <li key={s.key} className={`stage ${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
            {label(s.label)}
          </li>
        ))}
      </ol>
      <span className="muted small">Deal: {deal.name}{deal.is_closed ? " (closed)" : ""}</span>
    </div>
  );
}

export function DetailHeader(props: {
  crumb?: ReactNode; title: string; tags?: ReactNode; actions?: ReactNode; deal?: DealOut | null;
}) {
  return (
    <header className="detail-head">
      {props.crumb && <p className="crumb">{props.crumb}</p>}
      <div className="row between wrap">
        <h1>{props.title}</h1>
        {props.actions && <div className="row wrap">{props.actions}</div>}
      </div>
      {props.tags && <div className="row wrap">{props.tags}</div>}
      {props.deal && <StageRoadmap deal={props.deal} />}
    </header>
  );
}

/** Facts · timeline and documents · insights. Stacks under 1100px. */
export function Summary3(props: { facts: ReactNode; middle: ReactNode; insights: ReactNode }) {
  return (
    <div className="summary3">
      <div className="stack">{props.facts}</div>
      <div className="stack">{props.middle}</div>
      <div className="stack">{props.insights}</div>
    </div>
  );
}
