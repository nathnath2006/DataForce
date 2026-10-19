import { useState } from "react";
import { SourcePicker } from "./SourcePicker";
import {
  aggsFor, columnsOf, DEFAULT_OPTIONS, roleOf, SLOT_DEFS, STAR, VIZ_LABEL, VIZ_TYPES, type FieldRef, type SlotName,
  autoTitle,
} from "./spec";
import type { Agg, ColumnInfo, Source, Visualization, VizType } from "./types";

export const FIELD_MIME = "application/x-df-field";

const dtypeLabel = (d: string) => (d === "integer" || d === "number" ? "123" : d === "boolean" ? "T/F" : d.startsWith("date") ? "date" : "abc");

export function DataPanel(props: {
  source: Source | null; fields: ColumnInfo[] | null; error: string | null; nRows: number | null; truncated: boolean;
  onPickSource: (s: Source) => void; onAdd: (f: FieldRef) => void;
}) {
  const [q, setQ] = useState("");
  const match = (c: ColumnInfo) => c.name.toLowerCase().includes(q.toLowerCase());
  const dims = (props.fields ?? []).filter((c) => roleOf(c.dtype) === "dimension" && match(c));
  const meas = (props.fields ?? []).filter((c) => roleOf(c.dtype) === "measure" && match(c));
  const item = (f: FieldRef, label = f.name) => (
    <li key={f.name}>
      <button className="wb-field" draggable title="Click to add, or drag onto a slot"
        onDragStart={(e) => { e.dataTransfer.setData(FIELD_MIME, JSON.stringify(f)); e.dataTransfer.effectAllowed = "copy"; }}
        onClick={() => props.onAdd(f)}>
        <span className="wb-dt">{dtypeLabel(f.dtype)}</span>{label}
      </button>
    </li>
  );
  return (
    <aside className="card wb-side wb-edit" aria-label="Data">
      <h3>Data</h3>
      {props.source ? <SourcePicker value={props.source} onChange={props.onPickSource} /> : <p className="muted small">Add a visualization first.</p>}
      {props.error && <p className="note err small">{props.error}</p>}
      {props.nRows !== null && <p className="muted small">{props.nRows.toLocaleString("en-US")} rows{props.truncated ? " (capped)" : ""}</p>}
      {props.fields && (
        <>
          <input type="search" placeholder="Find a field" aria-label="Find a field" value={q} onChange={(e) => setQ(e.target.value)} />
          <h4>Measures</h4>
          <ul className="plain wb-fields">{item(STAR, "Number of rows")}{meas.map((c) => item(c))}</ul>
          <h4>Dimensions</h4>
          <ul className="plain wb-fields">{dims.map((c) => item(c))}</ul>
        </>
      )}
    </aside>
  );
}

export function GrammarPanel(props: {
  viz: Visualization; fields: ColumnInfo[] | null; onChange: (v: Visualization) => void;
  onType: (t: VizType) => void; onDrop: (f: FieldRef, slot: SlotName) => void;
  onRemove: (slot: SlotName, i: number) => void; onAgg: (slot: "values" | "size", i: number, a: Agg) => void;
  onDelete: () => void;
}) {
  const { viz } = props;
  const dt = columnsOf(props.fields ?? []);
  const chips = (slot: SlotName): { text: string; agg?: { slot: "values" | "size"; i: number; value: Agg; opts: Agg[] } }[] => {
    const s = viz.slots;
    const meas = (m: { column: string; agg: Agg }, slotName: "values" | "size", i: number) => ({
      text: m.column === "*" ? "Number of rows" : m.column,
      agg: { slot: slotName, i, value: m.agg, opts: aggsFor({ name: m.column, dtype: dt.get(m.column) ?? "text" }) },
    });
    switch (slot) {
      case "category": return s.category ? [{ text: s.category }] : [];
      case "color": return s.color ? [{ text: s.color }] : [];
      case "size": return s.size ? [meas(s.size, "size", 0)] : [];
      case "values": return s.values.map((m, i) => meas(m, "values", i));
      case "rows": return s.rows.map((text) => ({ text }));
      case "columns": return s.columns.map((text) => ({ text }));
    }
  };
  const o = viz.options;
  const set = (patch: Partial<typeof o>) => props.onChange({ ...viz, options: { ...o, ...patch } });
  const isCartesian = viz.type === "bar" || viz.type === "line" || viz.type === "area";
  return (
    <aside className="card wb-side wb-edit" aria-label="Grammar">
      <h3>Visualization</h3>
      <input aria-label="Title" placeholder={autoTitle(viz)} value={viz.title} maxLength={200} onChange={(e) => props.onChange({ ...viz, title: e.target.value })} />
      <div className="wb-types" role="group" aria-label="Chart type">
        {VIZ_TYPES.map((t) => (
          <button key={t} className={t === viz.type ? "on" : ""} aria-pressed={t === viz.type} onClick={() => props.onType(t)}>{VIZ_LABEL[t]}</button>
        ))}
      </div>
      {SLOT_DEFS[viz.type].map((d) => (
        <div key={d.slot} className="wb-slot"
          onDragOver={(e) => { if (e.dataTransfer.types.includes(FIELD_MIME)) { e.preventDefault(); e.currentTarget.classList.add("over"); } }}
          onDragLeave={(e) => e.currentTarget.classList.remove("over")}
          onDrop={(e) => {
            e.preventDefault(); e.currentTarget.classList.remove("over");
            try { props.onDrop(JSON.parse(e.dataTransfer.getData(FIELD_MIME)) as FieldRef, d.slot); } catch { /* not ours */ }
          }}>
          <span className="wb-slot-label">{d.label}{d.required ? " *" : ""}</span>
          <div className="wb-slot-chips">
            {chips(d.slot).map((c, i) => (
              <span key={i} className="wb-chip">
                {c.agg && c.agg.opts.length > 1 ? (
                  <select aria-label={`Aggregate of ${c.text}`} value={c.agg.value} onChange={(e) => props.onAgg(c.agg!.slot, c.agg!.i, e.target.value as Agg)}>
                    {c.agg.opts.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                ) : c.agg ? <em>{c.agg.value}</em> : null}
                <span>{c.text}</span>
                <button className="ghost" aria-label={`Remove ${c.text}`} onClick={() => props.onRemove(d.slot, i)}>×</button>
              </span>
            ))}
            {chips(d.slot).length === 0 && <span className="muted small">drop a {d.kind} here</span>}
          </div>
        </div>
      ))}
      <h4>Options</h4>
      <div className="stack wb-opts">
        {isCartesian && <label className="check"><input type="checkbox" checked={o.stacked} onChange={(e) => set({ stacked: e.target.checked })} /> Stacked</label>}
        {viz.type === "bar" && <label className="check"><input type="checkbox" checked={o.horizontal} onChange={(e) => set({ horizontal: e.target.checked })} /> Horizontal</label>}
        {viz.type === "line" && <label className="check"><input type="checkbox" checked={o.smooth} onChange={(e) => set({ smooth: e.target.checked })} /> Smooth</label>}
        <label className="check"><input type="checkbox" checked={o.show_labels} onChange={(e) => set({ show_labels: e.target.checked })} /> Value labels</label>
        <label>Max rows
          <input type="number" min={1} max={5000} value={o.limit}
            onChange={(e) => set({ limit: Math.min(5000, Math.max(1, Math.round(Number(e.target.value) || DEFAULT_OPTIONS.limit))) })} />
        </label>
      </div>
      <button className="danger" onClick={props.onDelete}>Delete visualization</button>
    </aside>
  );
}
