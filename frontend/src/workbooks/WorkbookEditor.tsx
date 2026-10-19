import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { useWs } from "../context";
import { ErrorNote, Loading, Tag, toApiError, useAction, useLoad } from "../ui";
import { AnalysisTabs } from "../analysis/AnalysisTabs";
import { wbApi } from "./api";
import { ExplainPanel } from "./ExplainPanel";
import { DataPanel, GrammarPanel } from "./panels";
import { sourceReady } from "./SourcePicker";
import {
  addField, changeType, crossFiltersFor, MAX_CANVASES, MAX_VIZ, moveItem, newViz, nextVizId, orderedLayout,
  packLayout, reduceCross, removeFromSlot, resizeItem, selectedValue, setAgg, SIZES, sourceKey, VIZ_LABEL, VIZ_TYPES, displayTitle,
  columnsOf, type CrossFilter, type FieldRef, type SlotName,
} from "./spec";
import type { Agg, Canvas, ColumnInfo, Filter, FilterOp, Source, Visualization, VizType, WorkbookSpec } from "./types";
import { VizTile } from "./VizTile";
import "./workbooks.css";

const DEFAULT_SOURCE: Source = { kind: "crm", table: "deals" };

interface FieldsState { cols: ColumnInfo[]; n: number; truncated: boolean }

/** Pack the layout before saving so stored x / y match what the grid shows. */
function normalized(spec: WorkbookSpec): WorkbookSpec {
  return { ...spec, canvases: spec.canvases.map((c) => ({ ...c, layout: packLayout(orderedLayout(c)) })) };
}

export function WorkbookEditorPage() {
  const { ws } = useWs();
  const { id = "" } = useParams();
  const wb = useLoad(() => wbApi.get(ws.slug, id), [ws.slug, id]);
  if (wb.loading && !wb.data) return <section className="stack"><AnalysisTabs /><Loading /></section>;
  if (!wb.data) return <section className="stack"><AnalysisTabs /><ErrorNote error={wb.error} /><Link to={`/w/${ws.slug}/analysis/workbooks`}>Back to workbooks</Link></section>;
  return <Editor key={wb.data.id} slug={ws.slug} id={wb.data.id} initialName={wb.data.name} initial={wb.data.spec} />;
}

function Editor(props: { slug: string; id: string; initialName: string; initial: WorkbookSpec }) {
  const { slug, id } = props;
  const [name, setName] = useState(props.initialName);
  const [spec, setSpec] = useState<WorkbookSpec>(() => (props.initial.canvases.length ? props.initial : { version: 1, canvases: [{ name: "Canvas 1", filters: [], layout: [], visualizations: [] }] }));
  const [saved, setSaved] = useState(() => JSON.stringify([props.initialName, normalized(props.initial)]));
  const [ci, setCi] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const [explain, setExplain] = useState(false);
  const [cross, dispatchCross] = useReducer(reduceCross, [] as CrossFilter[]);
  const [fields, setFields] = useState<Record<string, FieldsState | string>>({});
  const save = useAction();
  const canvas = spec.canvases[ci] ?? spec.canvases[0]!;
  const dirty = JSON.stringify([name, normalized(spec)]) !== saved;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Field lists of every source in use on this canvas (also tells cross-filters which columns apply).
  const sources = useMemo(() => {
    const m = new Map<string, Source>();
    for (const v of canvas.visualizations) if (sourceReady(v.source)) m.set(sourceKey(v.source), v.source);
    return [...m.entries()];
  }, [canvas.visualizations]);
  useEffect(() => {
    for (const [k, s] of sources) {
      if (fields[k] !== undefined) continue;
      setFields((f) => ({ ...f, [k]: { cols: [], n: 0, truncated: false } }));
      wbApi.fields(slug, s).then(
        (r) => setFields((f) => ({ ...f, [k]: { cols: r.columns, n: r.n_source_rows, truncated: r.truncated_source } })),
        (e: unknown) => setFields((f) => ({ ...f, [k]: toApiError(e).message })),
      );
    }
  }, [sources, slug, fields]);
  const fieldsOf = (s: Source | undefined): FieldsState | string | undefined => (s && sourceReady(s) ? fields[sourceKey(s)] : undefined);

  const patchCanvas = useCallback((fn: (c: Canvas) => Canvas) => {
    setSpec((sp) => ({ ...sp, canvases: sp.canvases.map((c, i) => (i === ci ? fn(c) : c)) }));
  }, [ci]);
  const patchViz = (vid: string, fn: (v: Visualization) => Visualization) =>
    patchCanvas((c) => ({ ...c, visualizations: c.visualizations.map((v) => (v.id === vid ? fn(v) : v)) }));

  const selected = canvas.visualizations.find((v) => v.id === sel) ?? null;
  const selFields = fieldsOf(selected?.source);
  const selCols = typeof selFields === "object" ? selFields.cols : null;

  const addViz = (type: VizType) => {
    if (canvas.visualizations.length >= MAX_VIZ) return;
    const last = canvas.visualizations.at(-1);
    const v = newViz(nextVizId(canvas), type, last?.source ?? DEFAULT_SOURCE);
    patchCanvas((c) => {
      const next = { ...c, visualizations: [...c.visualizations, v] };
      return { ...next, layout: packLayout([...orderedLayout(c), ...orderedLayout(next).slice(-1)]) };
    });
    setSel(v.id);
  };
  const deleteViz = (vid: string) => {
    patchCanvas((c) => ({ ...c, visualizations: c.visualizations.filter((v) => v.id !== vid), layout: c.layout.filter((l) => l.viz_id !== vid) }));
    dispatchCross({ type: "dropViz", vizId: vid });
    setSel(null);
  };
  const layout = useMemo(() => packLayout(orderedLayout(canvas)), [canvas]);
  const setLayout = (l: ReturnType<typeof packLayout>) => patchCanvas((c) => ({ ...c, layout: l }));

  const colSetFor = (s: Source): ReadonlySet<string> | null => {
    const f = fieldsOf(s);
    return typeof f === "object" ? new Set(f.cols.map((c) => c.name)) : null;
  };
  const filtersFor = (v: Visualization): Filter[] => [...canvas.filters, ...crossFiltersFor(cross, v.id, colSetFor(v.source))];

  const doSave = () => save.run(async () => {
    const body = normalized(spec);
    const out = await wbApi.update(slug, id, { name: name.trim() || "Untitled", spec: body });
    setSaved(JSON.stringify([out.name, normalized(out.spec)]));
    setName(out.name);
  });

  const dragId = useRef<string | null>(null);
  const dtypes = useMemo(() => columnsOf(selCols ?? []), [selCols]);
  const onField = (f: FieldRef, slot?: SlotName) => { if (selected) patchViz(selected.id, (v) => addField(v, f, slot)); };

  return (
    <section className="stack wb">
      <AnalysisTabs />
      <div className="row between wrap">
        <div className="row wrap">
          <Link to={`/w/${slug}/analysis/workbooks`}>Workbooks</Link><span className="muted">/</span>
          <input className="wb-name" aria-label="Workbook name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
          {dirty && <Tag kind="warn">unsaved</Tag>}
        </div>
        <div className="row wrap">
          <label className="wb-edit wb-add check">Add
            <select value="" aria-label="Add a visualization" onChange={(e) => { if (e.target.value) addViz(e.target.value as VizType); }}>
              <option value="">visualization…</option>
              {VIZ_TYPES.map((t) => <option key={t} value={t}>{VIZ_LABEL[t]}</option>)}
            </select>
          </label>
          <button className="wb-edit" aria-pressed={explain} onClick={() => setExplain((x) => !x)} disabled={!selCols}>Explain</button>
          <button className="primary wb-edit" disabled={!dirty || save.busy} onClick={() => void doSave()}>{save.busy ? "Saving…" : "Save"}</button>
        </div>
      </div>
      <ErrorNote error={save.error} />

      <div className="wb-tabs" role="tablist" aria-label="Canvases">
        {spec.canvases.map((c, i) => (
          <button key={i} role="tab" aria-selected={i === ci} className={i === ci ? "on" : ""}
            onClick={() => { setCi(i); setSel(null); dispatchCross({ type: "clear" }); }}>{c.name}</button>
        ))}
        {spec.canvases.length < MAX_CANVASES && (
          <button className="wb-edit" aria-label="Add canvas" onClick={() => {
            setSpec((s) => ({ ...s, canvases: [...s.canvases, { name: `Canvas ${s.canvases.length + 1}`, filters: [], layout: [], visualizations: [] }] }));
            setCi(spec.canvases.length); setSel(null); dispatchCross({ type: "clear" });
          }}>+</button>
        )}
        <span className="wb-edit row">
          <input aria-label="Canvas name" value={canvas.name} maxLength={100} onChange={(e) => patchCanvas((c) => ({ ...c, name: e.target.value || " " }))} />
          {spec.canvases.length > 1 && (
            <button className="danger" onClick={() => {
              setSpec((s) => ({ ...s, canvases: s.canvases.filter((_, i) => i !== ci) }));
              setCi(0); setSel(null); dispatchCross({ type: "clear" });
            }}>Delete canvas</button>
          )}
        </span>
      </div>

      <FiltersBar filters={canvas.filters} cols={selCols ?? (typeof Object.values(fields)[0] === "object" ? (Object.values(fields)[0] as FieldsState).cols : [])}
        cross={cross} onChange={(f) => patchCanvas((c) => ({ ...c, filters: f }))} dispatch={dispatchCross} />

      <div className={`wb-layout ${explain ? "with-explain" : ""}`}>
        <DataPanel
          source={selected?.source ?? null}
          fields={selCols} error={typeof selFields === "string" ? selFields : null}
          nRows={typeof selFields === "object" ? selFields.n : null} truncated={typeof selFields === "object" && selFields.truncated}
          onPickSource={(s) => selected && patchViz(selected.id, (v) => ({ ...v, source: s, slots: newViz(v.id, v.type, s).slots }))}
          onAdd={(f) => onField(f)}
        />
        <div className="wb-canvas" aria-label="Canvas">
          {canvas.visualizations.length === 0 && <p className="muted empty">Empty canvas. Use “Add visualization”, then click or drag fields onto it.</p>}
          {layout.map((it) => {
            const v = canvas.visualizations.find((x) => x.id === it.viz_id);
            if (!v) return null;
            const pickedBy = selectedValue(cross, v.id);
            return (
              <article key={v.id} className={`card wb-tile ${sel === v.id ? "sel" : ""}`}
                style={{ gridColumn: `span ${it.w}`, minHeight: `${it.h * 56}px` }}
                onClick={() => setSel(v.id)}
                onDragOver={(e) => { if (dragId.current) e.preventDefault(); }}
                onDrop={(e) => { e.preventDefault(); if (dragId.current) setLayout(moveItem(layout, dragId.current, v.id)); dragId.current = null; }}>
                <header className="row between">
                  <strong className="wb-tile-title" draggable onDragStart={(e) => { dragId.current = v.id; e.dataTransfer.setData("text/plain", v.id); }}
                    title={`${displayTitle(v)} (drag to reorder)`}>{displayTitle(v)}</strong>
                  <span className="row wb-edit wb-tile-ctl">
                    <select aria-label="Width" value={it.w} onClick={(e) => e.stopPropagation()} onChange={(e) => setLayout(resizeItem(layout, v.id, Number(e.target.value), it.h))}>
                      {SIZES.map((w) => <option key={w} value={w}>{w}/12</option>)}
                    </select>
                    <button className="ghost" aria-label="Taller" onClick={(e) => { e.stopPropagation(); setLayout(resizeItem(layout, v.id, it.w, it.h + 1)); }}>+</button>
                    <button className="ghost" aria-label="Shorter" onClick={(e) => { e.stopPropagation(); setLayout(resizeItem(layout, v.id, it.w, it.h - 1)); }}>−</button>
                  </span>
                </header>
                {sourceReady(v.source)
                  ? <VizTile ws={slug} viz={v} filters={filtersFor(v)} selected={sel === v.id} picked={pickedBy?.label ?? null}
                      onPick={(p) => dispatchCross({ type: "toggle", filter: { vizId: v.id, column: p.column, value: p.value, label: p.label } })} />
                  : <p className="muted small">Choose a flow block in the Data panel.</p>}
              </article>
            );
          })}
        </div>
        {explain && selected && selCols ? (
          <ExplainPanel ws={slug} source={selected.source} fields={selCols} filters={filtersFor(selected)} onClose={() => setExplain(false)}
            preferred={[selected.slots.category, selected.slots.color, ...selected.slots.rows, ...selected.slots.columns].filter((x): x is string => !!x)} />
        ) : selected ? (
          <GrammarPanel viz={selected} fields={selCols}
            onChange={(v) => patchViz(selected.id, () => v)}
            onType={(t) => patchViz(selected.id, (v) => changeType(v, t, dtypes))}
            onDrop={onField} onRemove={(slot, i) => patchViz(selected.id, (v) => removeFromSlot(v, slot, i))}
            onAgg={(slot, i, a: Agg) => patchViz(selected.id, (v) => setAgg(v, slot, i, a))}
            onDelete={() => deleteViz(selected.id)} />
        ) : (
          <aside className="card wb-side wb-edit"><h3>Visualization</h3><p className="muted small">Select a visualization to edit it.</p></aside>
        )}
      </div>
      <p className="muted small">Every number comes from a server query over the chosen source, computed exactly. Click a mark to filter the other visualizations.</p>
    </section>
  );
}

const OPS: { op: FilterOp; label: string }[] = [
  { op: "eq", label: "is" }, { op: "ne", label: "is not" }, { op: "contains", label: "contains" }, { op: "gt", label: ">" },
  { op: "ge", label: "≥" }, { op: "lt", label: "<" }, { op: "le", label: "≤" }, { op: "is_null", label: "is empty" }, { op: "not_null", label: "is not empty" },
];

function FiltersBar(props: {
  filters: Filter[]; cols: ColumnInfo[]; cross: CrossFilter[]; onChange: (f: Filter[]) => void;
  dispatch: (a: Parameters<typeof reduceCross>[1]) => void;
}) {
  const [col, setCol] = useState("");
  const [op, setOp] = useState<FilterOp>("eq");
  const [val, setVal] = useState("");
  const nullary = op === "is_null" || op === "not_null";
  const kind = props.cols.find((c) => c.name === col)?.dtype;
  const add = () => {
    if (!col) return;
    const value = nullary ? undefined : kind === "number" || kind === "integer" ? Number(val) : kind === "boolean" ? val === "true" : val;
    props.onChange([...props.filters, { column: col, op, ...(value === undefined ? {} : { value }) }]);
    setVal("");
  };
  return (
    <div className="wb-filters row wrap" aria-label="Filters">
      {props.filters.map((f, i) => (
        <span key={i} className="wb-chip filter">
          {f.column} {OPS.find((o) => o.op === f.op)?.label} {f.value === undefined ? "" : String(f.value)}
          <button className="ghost wb-edit-inline" aria-label={`Remove filter on ${f.column}`} onClick={() => props.onChange(props.filters.filter((_, j) => j !== i))}>×</button>
        </span>
      ))}
      {props.cross.map((c) => (
        <span key={c.vizId + c.column} className="wb-chip cross" title="Selected in a visualization">
          {c.column}: {c.label}
          <button className="ghost" aria-label={`Remove selection on ${c.column}`} onClick={() => props.dispatch({ type: "remove", vizId: c.vizId, column: c.column })}>×</button>
        </span>
      ))}
      {props.cross.length > 1 && <button className="link" onClick={() => props.dispatch({ type: "clear" })}>Clear selections</button>}
      <span className="row wrap wb-edit">
        <select aria-label="Filter column" value={col} onChange={(e) => setCol(e.target.value)}>
          <option value="">Add filter…</option>
          {props.cols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        {col && (
          <>
            <select aria-label="Filter operator" value={op} onChange={(e) => setOp(e.target.value as FilterOp)}>
              {OPS.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
            </select>
            {!nullary && (kind === "boolean"
              ? <select aria-label="Filter value" value={val} onChange={(e) => setVal(e.target.value)}><option value="">choose</option><option value="true">true</option><option value="false">false</option></select>
              : <input aria-label="Filter value" value={val} onChange={(e) => setVal(e.target.value)} type={kind === "number" || kind === "integer" ? "number" : kind === "date" ? "date" : "text"} />)}
            <button onClick={add} disabled={!nullary && val === ""}>Add</button>
          </>
        )}
      </span>
    </div>
  );
}
