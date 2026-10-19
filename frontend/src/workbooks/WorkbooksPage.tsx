import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useWs } from "../context";
import { AnalysisTabs } from "../analysis/AnalysisTabs";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, useAction, useLoad } from "../ui";
import { wbApi } from "./api";
import type { WorkbookSummary } from "./types";

export function WorkbooksPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const list = useLoad(() => wbApi.list(ws.slug), [ws.slug]);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<WorkbookSummary | null>(null);
  const dup = useAction();
  return (
    <section className="stack">
      <AnalysisTabs />
      <div className="row between wrap">
        <h1>Workbooks</h1>
        <button className="primary" onClick={() => setCreating(true)}>New workbook</button>
      </div>
      <ErrorNote error={list.error} />
      <ErrorNote error={dup.error} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <Empty>No workbook yet. A workbook holds canvases of charts built from CRM tables or flow results.</Empty>}
      {list.data && list.data.length > 0 && (
        <div className="card tablewrap"><table>
          <thead><tr><th>Name</th><th className="num">Canvases</th><th>Updated</th><th /></tr></thead>
          <tbody>{list.data.map((w) => (
            <tr key={w.id}>
              <td><Link to={`/w/${ws.slug}/analysis/workbooks/${w.id}`}>{w.name}</Link></td>
              <td className="num">{w.n_canvases}</td>
              <td>{new Date(w.updated_at).toLocaleString()}</td>
              <td className="row end">
                <button disabled={dup.busy} onClick={() => void dup.run(async () => { await wbApi.duplicate(ws.slug, w.id); list.reload(); })}>Duplicate</button>
                <button className="danger" onClick={() => setDeleting(w)}>Delete</button>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {creating && <NewWorkbook slug={ws.slug} onClose={() => setCreating(false)} onCreated={(id) => nav(`/w/${ws.slug}/analysis/workbooks/${id}`)} />}
      {deleting && (
        <Confirm title="Delete workbook" confirmLabel="Delete" danger onClose={() => setDeleting(null)}
          onConfirm={async () => { await wbApi.remove(ws.slug, deleting.id); list.reload(); }}>
          <p>Delete <strong>{deleting.name}</strong>? This cannot be undone.</p>
        </Confirm>
      )}
    </section>
  );
}

function NewWorkbook(props: { slug: string; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const a = useAction();
  return (
    <Modal title="New workbook" onClose={props.onClose}>
      <form className="stack" onSubmit={(ev) => {
        ev.preventDefault();
        void a.run(async () => { const w = await wbApi.create(props.slug, { name: name.trim() }); props.onClose(); props.onCreated(w.id); });
      }}>
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus /></Field>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={name.trim() === "" || a.busy}>Create</button>
        </div>
      </form>
    </Modal>
  );
}
