import { useState, type ReactNode } from "react";
import { label } from "../lib";
import { roadmapSteps } from "../shell/logic";
import type { DealStage } from "../types";
import "./record.css";

export interface RecordAction {
  key: string; label: string; icon?: ReactNode; onClick: () => void;
  kind?: "primary" | "danger"; disabled?: boolean;
}
export interface RecordField { label: string; value: ReactNode }
export interface RecordTab { key: string; label: string; content: ReactNode }

export interface RecordPageProps {
  crumb?: ReactNode;
  title: string;
  subtitle?: ReactNode;
  tags?: ReactNode;
  /** Command bar. Skip an action by not passing it (e.g. Delete when not allowed). */
  actions?: RecordAction[];
  /** 3 to 5 key fields. */
  fields?: RecordField[];
  owner?: RecordField;
  /** The process bar, usually <ProcessBar />. */
  process?: ReactNode;
  tabs: RecordTab[];
  tab?: string; onTab?: (key: string) => void;
  children?: ReactNode;
}

function CommandBar({ actions }: { actions: RecordAction[] }) {
  const [open, setOpen] = useState(false);
  if (actions.length === 0) return null;
  const btn = (a: RecordAction, extra = "") => (
    <button key={a.key} type="button" className={`cmd ${a.kind ?? ""} ${extra}`} disabled={a.disabled}
      onClick={() => { setOpen(false); a.onClick(); }}>
      {a.icon}<span>{a.label}</span>
    </button>
  );
  const [first, ...rest] = actions;
  return (
    <div className="cmdbar" role="toolbar" aria-label="Actions">
      {actions.map((a) => btn(a, "cmd-wide"))}
      <span className="cmd-narrow">
        {btn(first!)}
        {rest.length > 0 && (
          <span className="cmd-more">
            <button type="button" className="cmd" aria-haspopup="menu" aria-expanded={open} aria-label="More actions" onClick={() => setOpen((o) => !o)}>⋯</button>
            {open && <div className="cmd-menu" role="menu">{rest.map((a) => btn(a))}</div>}
          </span>
        )}
      </span>
    </div>
  );
}

export function RecordPage(p: RecordPageProps) {
  const [inner, setInner] = useState(p.tabs[0]?.key ?? "");
  const active = p.tab ?? inner;
  const cur = p.tabs.find((t) => t.key === active) ?? p.tabs[0];
  const fields = [...(p.fields ?? []), ...(p.owner ? [p.owner] : [])];
  return (
    <section className="record">
      <CommandBar actions={p.actions ?? []} />
      <header className="rec-head">
        {p.crumb && <p className="crumb">{p.crumb}</p>}
        <div className="rec-title">
          <h1>{p.title}</h1>
          {p.tags && <div className="row wrap">{p.tags}</div>}
        </div>
        {p.subtitle && <p className="muted rec-sub">{p.subtitle}</p>}
        {fields.length > 0 && (
          <dl className="rec-fields">
            {fields.map((f) => <div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}
          </dl>
        )}
      </header>
      {p.process}
      <div className="rec-tabs" role="tablist">
        {p.tabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={t.key === cur?.key} className={t.key === cur?.key ? "on" : ""}
            onClick={() => { setInner(t.key); p.onTab?.(t.key); }}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" className="rec-panel">{cur?.content}</div>
      {p.children}
    </section>
  );
}

/** Two-column Summary: main on the left, side (timeline, AI) on the right; stacks on phone. */
export function SummaryLayout({ main, side }: { main: ReactNode; side: ReactNode }) {
  return (
    <div className="rec-summary">
      <div className="stack">{main}</div>
      <div className="stack">{side}</div>
    </div>
  );
}

/** Business-process stage bar for a deal stage. */
export function ProcessBar({ stage, name }: { stage: DealStage; name?: string }) {
  const steps = roadmapSteps(stage);
  return (
    <ol className="process" aria-label={`Stage${name ? ` of ${name}` : ""}: ${label(stage)}`}>
      {steps.map((s) => (
        <li key={s.key} className={`pstep ${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
          <span className="pdot" aria-hidden="true">{s.state === "done" ? "✓" : ""}</span>{label(s.label)}
        </li>
      ))}
    </ol>
  );
}
