import { useState } from "react";
import { Link } from "react-router";
import { useWs } from "../context";
import { Empty, ErrorNote, Loading, Modal, Tag, useAction, useLoad } from "../ui";
import { titlesApi, type NormalizeResult } from "./api";
import { ClassPicker, sourceKind } from "./TitleClass";
import { classLabel, sourceLabel } from "../orgchart/model";

export function NormalizeButton({ onDone }: { onDone: () => void }) {
  const { ws } = useWs();
  const [open, setOpen] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [res, setRes] = useState<NormalizeResult | null>(null);
  const act = useAction();
  return (
    <>
      <button onClick={() => { setOpen(true); setRes(null); }}>Normalize titles</button>
      {open && (
        <Modal title="Normalize titles" onClose={() => { setOpen(false); if (res) onDone(); }}>
          <div className="stack">
            <p>Reads every contact's job title and fills in a function and a seniority. Titles you set by hand are never changed.</p>
            <label className="check">
              <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
              Use AI for unknown titles
            </label>
            <p className="muted small">
              When ticked, only the title text of titles the dictionary cannot read is sent to the AI model. Names and any other data are never sent.
              Results are marked "AI" and flagged for your check.
            </p>
            <ErrorNote error={act.error} />
            {res && (
              <div role="status">
                <p>{res.n_contacts} contact(s) processed, {res.n_flagged} flagged for review.
                  {" "}Dictionary {res.by_source.dictionary ?? 0}, AI {res.by_source.llm ?? 0}, manual {res.by_source.manual ?? 0}, unknown {res.by_source.unknown ?? 0}.</p>
                {useAi && !res.ai_configured && <p className="muted small">No AI model is configured, so unknown titles were left unknown.</p>}
              </div>
            )}
            <div className="row end">
              <button onClick={() => { setOpen(false); if (res) onDone(); }}>Close</button>
              <button className="primary" disabled={act.busy} onClick={() => void act.run(async () => setRes(await titlesApi.normalize(ws.slug, useAi)))}>
                {act.busy ? "Working…" : "Run"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

export function ReviewTitles({ onChanged }: { onChanged: () => void }) {
  const { ws } = useWs();
  const r = useLoad(() => titlesApi.review(ws.slug), [ws.slug]);
  const [editId, setEditId] = useState<string | null>(null);
  const act = useAction();
  if (r.loading && !r.data) return <Loading />;
  return (
    <div className="stack">
      <ErrorNote error={r.error} />
      <ErrorNote error={act.error} />
      {r.data && r.data.length === 0 ? <Empty>Nothing to review.</Empty> : r.data && (
        <div className="tablewrap"><table>
          <thead><tr><th>Name</th><th>Title</th><th>Account</th><th>Class</th><th>Why</th></tr></thead>
          <tbody>{r.data.map((it) => (
            <tr key={it.contact_id}>
              <td><Link to={it.contact_id}>{it.full_name}</Link></td>
              <td>{it.title ?? "—"}</td>
              <td><Link to={`/w/${ws.slug}/accounts/${it.account_id}`}>{it.account_name}</Link></td>
              <td>{editId === it.contact_id ? (
                <ClassPicker fn={it.function} sen={it.seniority} busy={act.busy} onCancel={() => setEditId(null)}
                  onSave={(fn, sen) => void act.run(async () => {
                    await titlesApi.setClass(ws.slug, it.contact_id, { function: fn, seniority: sen });
                    setEditId(null); r.reload(); onChanged();
                  })} />
              ) : (
                <>{classLabel(it.function, it.seniority)} <Tag kind={sourceKind(it.source)}>{sourceLabel(it.source)}</Tag>{" "}
                  <button className="link" onClick={() => setEditId(it.contact_id)}>Fix</button></>
              )}</td>
              <td className="small">{it.flag ?? "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}
