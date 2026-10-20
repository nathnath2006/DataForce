import { useState } from "react";
import { adminApi } from "./api";
import { groupLimits, limitProblem } from "./m6format";
import type { EditableLimit as Limit } from "../api.gen";
import { Empty, ErrorNote, Loading, useAction, useLoad } from "../ui";

/** Admin page section: the limits, editable. `ws` null edits the global values (superadmin). */
export function Limits({ ws, readOnly = false, scope, onScope }: {
  ws: string | null; readOnly?: boolean;
  /** Superadmin only: shows the "Limits for" switch in the card header. */
  scope?: "ws" | "global"; onScope?: (v: "ws" | "global") => void;
}) {
  const lim = useLoad(() => adminApi.limits(ws), [ws]);
  return (
    <div className="card stack">
      <div className="row between wrap">
        <h2>Limits</h2>
        {scope && onScope && (
          <label className="row lim-scope">Limits for
            <select value={scope} onChange={(e) => onScope(e.target.value as "ws" | "global")}>
              <option value="ws">This workspace</option><option value="global">Global</option>
            </select>
          </label>
        )}
      </div>
      {readOnly && <p className="muted small">Not available in the demo: limits are read-only here.</p>}
      <p className="muted small">
        {ws ? "A workspace value can only be lower than the global one. Reset goes back to the global value." : "Global values, used by every workspace unless it sets a lower one. Reset goes back to the default."}
      </p>
      <ErrorNote error={lim.error} />
      {lim.loading && !lim.data ? <Loading /> : (lim.data ?? []).length === 0 ? <Empty>No limits.</Empty> : (
        groupLimits(lim.data ?? []).map(([group, rows]) => (
          <div key={group} className="lim-group">
            <h3 className="lim-title">{group}</h3>
            {rows.map((l) => <LimitRow key={`${ws}/${l.key}/${l.value}/${l.source}`} ws={ws} l={l} onSaved={lim.reload} readOnly={readOnly} />)}
          </div>
        ))
      )}
    </div>
  );
}

function LimitRow({ ws, l, onSaved, readOnly }: { ws: string | null; l: Limit; onSaved: () => void; readOnly: boolean }) {
  const [text, setText] = useState(String(l.value));
  const a = useAction();
  const problem = limitProblem(l, text);
  const dirty = text !== String(l.value);
  const save = (value: number | null) => void a.run(async () => { await adminApi.setLimit(ws, l.key, value); onSaved(); });
  const id = `lim-${l.key}`;
  return (
    <div className="lim-row">
      <div className="lim-label">
        <label htmlFor={id}>{l.description || l.key.replace(/_/g, " ")}</label>
        <code className="muted small" title={l.key}>{l.key}</code>
      </div>
      <div className="lim-edit">
        <input id={id} type="number" inputMode="numeric" value={text} min={l.min} max={l.max} step={l.kind === "float" ? "any" : 1}
          disabled={readOnly} onChange={(e) => setText(e.target.value)} aria-invalid={dirty && !!problem} />
        {l.unit && <span className="muted small">{l.unit}</span>}
        <button type="button" className={dirty ? "primary" : ""} disabled={readOnly || a.busy || !dirty || !!problem} onClick={() => save(Number(text))}>Save</button>
        <button type="button" className="lim-reset" disabled={readOnly || a.busy || l.source === "default"} onClick={() => save(null)}>Reset</button>
      </div>
      <p className="muted small lim-meta">
        Default {l.default.toLocaleString()} · allowed {l.min.toLocaleString()}–{l.max.toLocaleString()} · source: {l.source}
      </p>
      {dirty && problem && <p className="small lim-meta" role="alert">{problem}</p>}
      <ErrorNote error={a.error} />
    </div>
  );
}
