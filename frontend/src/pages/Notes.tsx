import { useState } from "react";
import { api } from "../api";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import type { NoteOut } from "../types";
import { Confirm, Empty, ErrorNote, Loading, Modal, Tag, useAction, useLoad } from "../ui";

type Kind = "note" | "comment";

/** Notes (on a contact) and comments (on an account): append-only threads. */
export function NoteThread({ kind, parentId }: { kind: Kind; parentId: string }) {
  const { ws, actingAs } = useWs();
  const list = useLoad(
    () => (kind === "note" ? api.listNotes(ws.slug, parentId) : api.listComments(ws.slug, parentId)),
    [ws.slug, parentId, kind]);
  const [body, setBody] = useState("");
  const [correcting, setCorrecting] = useState<NoteOut | null>(null);
  const [deleting, setDeleting] = useState<NoteOut | null>(null);
  const [history, setHistory] = useState<NoteOut | null>(null);
  const add = useAction();
  const noun = kind === "note" ? "note" : "comment";
  return (
    <div className="stack">
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void add.run(async () => {
          const b = { body: body.trim(), author_id: actingAs };
          if (kind === "note") await api.addNote(ws.slug, parentId, b); else await api.addComment(ws.slug, parentId, b);
          setBody("");
          list.reload();
        });
      }}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} maxLength={20000}
          placeholder={`Add a ${noun}${actingAs ? "" : " (nobody selected under “Acting as”)"}`} aria-label={`New ${noun}`} />
        <ErrorNote error={add.error} />
        <div className="row end"><button className="primary" disabled={add.busy || body.trim() === ""}>Add {noun}</button></div>
      </form>
      <ErrorNote error={list.error} />
      {list.loading && !list.data ? <Loading /> : list.data && list.data.length === 0 ? <Empty>No {noun}s yet.</Empty> : (
        <ul className="notes">
          {list.data?.map((n) => (
            <li key={n.id} className={n.deleted_at ? "deleted" : ""}>
              <div className="meta">
                <strong>{n.author_name ?? "unknown"}</strong> · {formatDateTime(n.created_at)}
                {n.corrects_id && <> <Tag kind="mute">corrected</Tag></>}
                {n.deleted_at && <> <Tag kind="bad">deleted</Tag></>}
              </div>
              {n.deleted_at
                ? <p className="muted">Deleted{n.deleted_by_name ? ` by ${n.deleted_by_name}` : ""} on {formatDateTime(n.deleted_at)}.</p>
                : <p className="pre">{n.body}</p>}
              <div className="row small">
                {!n.deleted_at && <button className="link" onClick={() => setCorrecting(n)}>Correct</button>}
                {!n.deleted_at && <button className="link" onClick={() => setDeleting(n)}>Delete</button>}
                <button className="link" onClick={() => setHistory(n)}>History</button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {correcting && (
        <CorrectDialog kind={kind} note={correcting} onClose={() => setCorrecting(null)} onDone={list.reload} />
      )}
      {deleting && (
        <Confirm title={`Delete ${noun}`} confirmLabel="Delete" danger onClose={() => setDeleting(null)}
          onConfirm={async () => {
            if (kind === "note") await api.deleteNote(ws.slug, deleting.id, actingAs);
            else await api.deleteComment(ws.slug, deleting.id, actingAs);
            list.reload();
          }}>
          <p>The {noun} is marked as deleted. It stays in the history; nothing is erased.</p>
        </Confirm>
      )}
      {history && <HistoryDrawer kind={kind} note={history} onClose={() => setHistory(null)} />}
    </div>
  );
}

function CorrectDialog(props: { kind: Kind; note: NoteOut; onClose: () => void; onDone: () => void }) {
  const { ws, actingAs } = useWs();
  const [body, setBody] = useState(props.note.body);
  const a = useAction();
  return (
    <Modal title={`Correct ${props.kind}`} onClose={props.onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void a.run(async () => {
          const b = { body: body.trim(), author_id: actingAs };
          if (props.kind === "note") await api.correctNote(ws.slug, props.note.id, b);
          else await api.correctComment(ws.slug, props.note.id, b);
          props.onDone();
          props.onClose();
        });
      }}>
        <p className="muted">Saving adds a new version. The original stays in the history.</p>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} maxLength={20000} aria-label="Corrected text" />
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy || body.trim() === ""}>Save correction</button>
        </div>
      </form>
    </Modal>
  );
}

function HistoryDrawer(props: { kind: Kind; note: NoteOut; onClose: () => void }) {
  const { ws } = useWs();
  const h = useLoad(
    () => (props.kind === "note" ? api.noteHistory(ws.slug, props.note.id) : api.commentHistory(ws.slug, props.note.id)),
    [ws.slug, props.note.id]);
  return (
    <Modal title="History (oldest first)" onClose={props.onClose} wide>
      <ErrorNote error={h.error} />
      {h.loading && !h.data ? <Loading /> : (
        <ul className="notes">
          {h.data?.map((n) => (
            <li key={n.id} className={n.deleted_at ? "deleted" : ""}>
              <div className="meta">
                <strong>{n.author_name ?? "unknown"}</strong> · {formatDateTime(n.created_at)}
                {n.deleted_at && <> <Tag kind="bad">deleted {formatDateTime(n.deleted_at)}{n.deleted_by_name ? ` by ${n.deleted_by_name}` : ""}</Tag></>}
              </div>
              <p className="pre">{n.body}</p>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
