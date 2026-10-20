import { useState } from "react";
import { adminApi } from "./api";
import { groupLimits, limitProblem } from "./m6format";
import type { EditableLimit as Limit } from "../api.gen";
import { Empty, ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";

/** Admin page section: the limits, editable. `ws` null edits the global values (superadmin). */
export function Limits({ ws }: { ws: string | null }) {
  const lim = useLoad(() => adminApi.limits(ws), [ws]);
  return (
    <div className="card stack">
      <h2>Limits</h2>
      <p className="muted small">
        {ws ? "A workspace value can only be lower than the global one. Reset goes back to the global value." : "Global values, used by every workspace unless it sets a lower one. Reset goes back to the default."}
      </p>
      <ErrorNote error={lim.error} />
      {lim.loading && !lim.data ? <Loading /> : (lim.data ?? []).length === 0 ? <Empty>No limits.</Empty> : (
        groupLimits(lim.data ?? []).map(([group, rows]) => (
          <div key={group} className="stack">
            <h3>{group}</h3>
            {rows.map((l) => <LimitRow key={`${ws}/${l.key}/${l.value}/${l.source}`} ws={ws} l={l} onSaved={lim.reload} />)}
          </div>
        ))
      )}
    </div>
  );
}

function LimitRow({ ws, l, onSaved }: { ws: string | null; l: Limit; onSaved: () => void }) {
  const [text, setText] = useState(String(l.value));
  const a = useAction();
  const problem = limitProblem(l, text);
  const dirty = text !== String(l.value);
  const save = (value: number | null) => void a.run(async () => { await adminApi.setLimit(ws, l.key, value); onSaved(); });
  return (
    <div className="stack">
      <div className="row wrap">
        <label className="grow">{l.key.replace(/_/g, " ")}{l.unit ? ` (${l.unit})` : ""}
          <input type="number" inputMode="numeric" value={text} min={l.min} max={l.max} step={l.kind === "float" ? "any" : 1}
            onChange={(e) => setText(e.target.value)} aria-invalid={dirty && !!problem} />
        </label>
        <button type="button" className="primary" disabled={a.busy || !dirty || !!problem} onClick={() => save(Number(text))}>Save</button>
        <button type="button" disabled={a.busy || l.source === "default"} onClick={() => save(null)}>Reset</button>
      </div>
      <p className="muted small">
        {l.description} Default {l.default.toLocaleString()}; allowed {l.min} to {l.max}.{" "}
        <Tag kind={l.source === "default" ? "mute" : "ok"}>{l.source}</Tag>
      </p>
      {dirty && problem && <p className="small" role="alert">{problem}</p>}
      <ErrorNote error={a.error} />
    </div>
  );
}
