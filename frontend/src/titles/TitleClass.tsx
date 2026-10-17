import { useState } from "react";
import { useWs } from "../context";
import { classLabel, sourceLabel } from "../orgchart/model";
import { ErrorNote, Tag, useAction } from "../ui";
import { FUNCTIONS, SENIORITIES, titlesApi } from "./api";

export function ClassPicker(props: {
  fn: string; sen: string; busy?: boolean; onSave: (fn: string, sen: string) => void; onCancel?: () => void;
}) {
  const [fn, setFn] = useState(props.fn);
  const [sen, setSen] = useState(props.sen);
  return (
    <span className="row wrap">
      <select aria-label="Function" value={fn} onChange={(e) => setFn(e.target.value)}>
        {FUNCTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
      </select>
      <select aria-label="Seniority" value={sen} onChange={(e) => setSen(e.target.value)}>
        {SENIORITIES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
      </select>
      <button className="primary" disabled={props.busy} onClick={() => props.onSave(fn, sen)}>Save</button>
      {props.onCancel && <button disabled={props.busy} onClick={props.onCancel}>Cancel</button>}
    </span>
  );
}

export function sourceKind(s: string | null | undefined): "ok" | "warn" | "mute" {
  return s === "manual" ? "ok" : s === "llm" ? "warn" : "mute";
}

/** Title class row for ContactDetail: class, source badge, flag, manual change. */
export function TitleClassRow(props: {
  contactId: string; fn: string | null; sen: string | null; source?: string | null; flag?: string | null; onChanged: () => void;
}) {
  const { ws } = useWs();
  const [editing, setEditing] = useState(false);
  const act = useAction();
  return (
    <>
      <dt>Title class</dt>
      <dd>
        {editing ? (
          <ClassPicker fn={props.fn ?? "unknown"} sen={props.sen ?? "unknown"} busy={act.busy} onCancel={() => setEditing(false)}
            onSave={(fn, sen) => void act.run(async () => {
              await titlesApi.setClass(ws.slug, props.contactId, { function: fn, seniority: sen });
              setEditing(false); props.onChanged();
            })} />
        ) : (
          <>
            {classLabel(props.fn, props.sen)} <Tag kind={sourceKind(props.source)}>{sourceLabel(props.source)}</Tag>{" "}
            <button className="link" onClick={() => setEditing(true)}>Change</button>
            {props.flag && <div><Tag kind="warn">check</Tag> <span className="small">{props.flag}</span></div>}
          </>
        )}
        <ErrorNote error={act.error} />
      </dd>
    </>
  );
}
