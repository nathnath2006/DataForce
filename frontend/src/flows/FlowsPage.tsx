import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useWs } from "../context";
import { AnalysisTabs } from "../analysis/AnalysisTabs";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, useAction, useLoad } from "../ui";
import { flowApi } from "./flowApi";
import { TEMPLATES, emptyGraph } from "./graph";
import type { FlowSummary } from "./types";
import "./flows.css";

export function FlowsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const list = useLoad(() => flowApi.list(ws.slug), [ws.slug]);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<FlowSummary | null>(null);
  const [deleting, setDeleting] = useState<FlowSummary | null>(null);
  return (
    <section className="stack">
      <AnalysisTabs />
      <div className="row between wrap">
        <h1>Analysis flows</h1>
        <div className="row">
          <Link to={`/w/${ws.slug}/analysis/scan`}>Quick scan</Link>
          <button className="primary" onClick={() => setCreating(true)}>New flow</button>
        </div>
      </div>
      <ErrorNote error={list.error} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <Empty>No flow yet. Create one from a template or start empty.</Empty>}
      {list.data && list.data.length > 0 && (
        <div className="card tablewrap"><table>
          <thead><tr><th>Name</th><th className="num">Blocks</th><th>Updated</th><th /></tr></thead>
          <tbody>{list.data.map((f) => (
            <tr key={f.id}>
              <td><Link to={`/w/${ws.slug}/analysis/${f.id}`}>{f.name}</Link>
                {f.description && <div className="muted small">{f.description}</div>}</td>
              <td className="num">{f.n_nodes}</td>
              <td>{new Date(f.updated_at).toLocaleString()}</td>
              <td className="row end">
                <button onClick={() => setRenaming(f)}>Rename</button>
                <button className="danger" onClick={() => setDeleting(f)}>Delete</button>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {creating && <NewFlow slug={ws.slug} onClose={() => setCreating(false)} onCreated={(id) => nav(`/w/${ws.slug}/analysis/${id}`)} />}
      {renaming && <Rename flow={renaming} slug={ws.slug} onClose={() => setRenaming(null)} onDone={() => { setRenaming(null); list.reload(); }} />}
      {deleting && (
        <Confirm title="Delete flow" confirmLabel="Delete" danger onClose={() => setDeleting(null)}
          onConfirm={async () => { await flowApi.remove(ws.slug, deleting.id); list.reload(); }}>
          <p>Delete <strong>{deleting.name}</strong>? This cannot be undone.</p>
        </Confirm>
      )}
    </section>
  );
}

function NewFlow(props: { slug: string; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [tpl, setTpl] = useState("");
  const a = useAction();
  const create = () => void a.run(async () => {
    const t = TEMPLATES.find((x) => x.key === tpl);
    const f = await flowApi.create(props.slug, {
      name: name.trim() || t?.title || "Untitled flow", graph: t ? t.build() : emptyGraph(),
    });
    props.onCreated(f.id);
  });
  return (
    <Modal title="New flow" onClose={props.onClose}>
      <div className="stack">
        <Field label="Name"><input value={name} maxLength={200} onChange={(ev) => setName(ev.target.value)} /></Field>
        <fieldset className="tpl-list">
          <legend>Start from</legend>
          <label className="tpl"><input type="radio" name="tpl" checked={tpl === ""} onChange={() => setTpl("")} /> Empty flow</label>
          {TEMPLATES.map((t) => (
            <label className="tpl" key={t.key}>
              <input type="radio" name="tpl" checked={tpl === t.key} onChange={() => setTpl(t.key)} />
              <span>{t.title}<span className="muted small"> {t.description}</span></span>
            </label>
          ))}
        </fieldset>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy} onClick={create}>Create</button>
        </div>
      </div>
    </Modal>
  );
}

function Rename(props: { flow: FlowSummary; slug: string; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(props.flow.name);
  const a = useAction();
  return (
    <Modal title="Rename flow" onClose={props.onClose}>
      <div className="stack">
        <Field label="Name"><input value={name} maxLength={200} onChange={(ev) => setName(ev.target.value)} /></Field>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy || !name.trim()}
            onClick={() => void a.run(async () => { await flowApi.update(props.slug, props.flow.id, { name: name.trim() }); props.onDone(); })}>
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
