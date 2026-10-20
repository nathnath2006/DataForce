import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useWs } from "../context";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, useAction, useLoad } from "../ui";
import { flowApi } from "./flowApi";
import { TEMPLATES, emptyGraph } from "./graph";
import type { FlowSummary } from "./types";
import "./flows.css";
import { Icon } from "../icons";

export function FlowsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const list = useLoad(() => flowApi.list(ws.slug), [ws.slug]);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<FlowSummary | null>(null);
  const [deleting, setDeleting] = useState<FlowSummary | null>(null);
  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>Analysis</h1>
          <p className="muted">Flows wire blocks together on a canvas. Every comparison and model says whether it is verified.</p>
        </div>
        <button className="primary" onClick={() => setCreating(true)}><Icon name="plus" size={18} />New flow</button>
      </div>
      <ErrorNote error={list.error} />
      {list.loading && !list.data && <Loading />}
      <div className="bento">
        <Link to={`/w/${ws.slug}/analysis/scan`} className="tile w4">
          <div className="tile-head"><span className="icon-badge"><Icon name="stats" /></span><Icon name="arrow" size={16} /></div>
          <h2>Quick scan</h2>
          <p className="muted small">Win rate, cycle and deal size across every segment, tested in one go.</p>
        </Link>
        <Link to={`/w/${ws.slug}/docs`} className="tile w4">
          <div className="tile-head"><span className="icon-badge"><Icon name="docs" /></span><Icon name="arrow" size={16} /></div>
          <h2>Reading the results</h2>
          <p className="muted small">What “not verified” and each warning mean, and what to do about them.</p>
        </Link>
        <button type="button" className="tile w4 new-tile" onClick={() => setCreating(true)}>
          <span className="icon-badge"><Icon name="plus" /></span>
          <h2>New flow</h2>
          <p className="muted small">Start empty or from a template.</p>
        </button>
        {list.data && list.data.length === 0 && <div className="tile"><Empty>No flow yet. Create one from a template or start empty.</Empty></div>}
        {list.data?.map((f) => (
          <article key={f.id} className="tile w4 flow-card">
            <div className="tile-head">
              <h2><Link to={`/w/${ws.slug}/analysis/${f.id}`}>{f.name}</Link></h2>
            </div>
            <p className="desc">{f.description || "No description."}</p>
            <div className="meta-row">
              <span><Icon name="analysis" size={14} /> {f.n_nodes} block{f.n_nodes === 1 ? "" : "s"}</span>
              <span>Updated {new Date(f.updated_at).toLocaleDateString()}</span>
            </div>
            <div className="actions">
              <Link className="btn quiet" to={`/w/${ws.slug}/analysis/${f.id}`}>Open</Link>
              <button className="quiet" onClick={() => setRenaming(f)}><Icon name="edit" size={16} />Rename</button>
              <button className="danger" onClick={() => setDeleting(f)}><Icon name="trash" size={16} />Delete</button>
            </div>
          </article>
        ))}
      </div>
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
