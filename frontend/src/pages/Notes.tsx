import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useWs } from "../context";
import { Icon } from "../icons";
import { formatDateTime } from "../lib";
import type { NoteOut } from "../types";
import { ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";
import { noteTitle, noteSnippet } from "./notesText";
import "./notes.css";

type Kind = "note" | "comment";
const NEW = "__new__";

/**
 * Notes (on a contact) and comments (on an account), Apple Notes style: the list on one side, the
 * selected one open on the other, no dialog. They stay append-only: editing saves a correction (a new
 * version, the old one stays in the history) and deleting only marks as deleted.
 */
export function NoteThread({ kind, parentId }: { kind: Kind; parentId: string }) {
  const { ws, actingAs } = useWs();
  const list = useLoad(
    () => (kind === "note" ? api.listNotes(ws.slug, parentId) : api.listComments(ws.slug, parentId)),
    [ws.slug, parentId, kind]);
  const notes = useMemo(() => list.data ?? [], [list.data]);
  const [sel, setSel] = useState<string | null>(null);
  const noun = kind === "note" ? "note" : "comment";

  // History is fetched ahead (on hover / focus / selection) so opening it never waits.
  const cache = useRef(new Map<string, Promise<NoteOut[]>>());
  const prefetch = (id: string) => {
    if (!cache.current.has(id)) {
      const p = kind === "note" ? api.noteHistory(ws.slug, id) : api.commentHistory(ws.slug, id);
      p.catch(() => cache.current.delete(id));
      cache.current.set(id, p);
    }
    return cache.current.get(id)!;
  };

  useEffect(() => {
    if (sel === NEW || (sel && notes.some((n) => n.id === sel))) return;
    setSel(notes.find((n) => !n.deleted_at)?.id ?? notes[0]?.id ?? NEW);
  }, [notes, sel]);

  const reload = (focus?: string) => { cache.current.clear(); if (focus) setSel(focus); list.reload(); };
  const current = notes.find((n) => n.id === sel) ?? null;

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const i = notes.findIndex((n) => n.id === sel);
    const next = notes[Math.min(notes.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) { setSel(next.id); document.getElementById(`ni-${next.id}`)?.focus(); }
  };

  return (
    <div className="notes-app">
      <div className="notes-list" role="listbox" aria-label={`${noun}s`} onKeyDown={onListKey}>
        <button type="button" className={`notes-new${sel === NEW ? " on" : ""}`} onClick={() => setSel(NEW)}>
          <Icon name="plus" size={16} />New {noun}
        </button>
        <ErrorNote error={list.error} />
        {list.loading && !list.data && <Loading />}
        {list.data && notes.length === 0 && <p className="muted small notes-empty">No {noun}s yet.</p>}
        {notes.map((n) => (
          <button type="button" key={n.id} id={`ni-${n.id}`} role="option" aria-selected={n.id === sel}
            className={`notes-item${n.id === sel ? " on" : ""}${n.deleted_at ? " deleted" : ""}`}
            onClick={() => setSel(n.id)} onMouseEnter={() => prefetch(n.id)} onFocus={() => prefetch(n.id)}>
            <span className="ni-title">{n.deleted_at ? "Deleted" : noteTitle(n.body)}</span>
            <span className="ni-meta">{formatDateTime(n.created_at)}{n.author_name ? ` · ${n.author_name}` : ""}</span>
            {!n.deleted_at && <span className="ni-snip">{noteSnippet(n.body)}</span>}
          </button>
        ))}
      </div>
      <div className="notes-pane">
        {sel === NEW
          ? <Composer key={`new-${parentId}`} kind={kind} parentId={parentId} actingAs={actingAs} onSaved={(id) => reload(id)} />
          : current && <NoteView key={current.id} kind={kind} note={current} history={() => prefetch(current.id)} onChanged={reload} />}
      </div>
    </div>
  );
}

function Composer(props: { kind: Kind; parentId: string; actingAs: string | null; onSaved: (id: string) => void }) {
  const { ws } = useWs();
  const [body, setBody] = useState("");
  const a = useAction();
  const noun = props.kind === "note" ? "note" : "comment";
  const save = () => void a.run(async () => {
    const b = { body: body.trim(), author_id: props.actingAs };
    const n = props.kind === "note" ? await api.addNote(ws.slug, props.parentId, b) : await api.addComment(ws.slug, props.parentId, b);
    setBody("");
    props.onSaved(n.id);
  });
  return (
    <div className="notes-editor">
      <p className="ne-meta">New {noun}{props.actingAs ? "" : " · nobody selected under “Acting as”"}</p>
      <textarea className="ne-body" value={body} autoFocus maxLength={20000} aria-label={`New ${noun}`}
        placeholder={`Start typing a ${noun}…`} onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && body.trim()) save(); }} />
      <ErrorNote error={a.error} />
      <div className="ne-bar">
        <span className="muted small">⌘/Ctrl + Enter to save</span>
        <button className="primary" disabled={a.busy || body.trim() === ""} onClick={save}>Add {noun}</button>
      </div>
    </div>
  );
}

function NoteView(props: { kind: Kind; note: NoteOut; history: () => Promise<NoteOut[]>; onChanged: (focus?: string) => void }) {
  const { ws, actingAs } = useWs();
  const n = props.note;
  const [body, setBody] = useState(n.body);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [hist, setHist] = useState<NoteOut[] | null>(null);
  const a = useAction();
  const changed = body.trim() !== n.body.trim() && body.trim() !== "";
  const noun = props.kind === "note" ? "note" : "comment";

  useEffect(() => {
    if (!showHistory) return;
    let live = true;
    props.history().then((h) => { if (live) setHist(h); }, () => { if (live) setHist([]); });
    return () => { live = false; };
  }, [showHistory, props]);

  const correct = () => void a.run(async () => {
    const b = { body: body.trim(), author_id: actingAs };
    const out = props.kind === "note" ? await api.correctNote(ws.slug, n.id, b) : await api.correctComment(ws.slug, n.id, b);
    props.onChanged(out.id);
  });
  const remove = () => void a.run(async () => {
    if (props.kind === "note") await api.deleteNote(ws.slug, n.id, actingAs);
    else await api.deleteComment(ws.slug, n.id, actingAs);
    setConfirmDelete(false);
    props.onChanged(n.id);
  });

  return (
    <div className="notes-editor">
      <p className="ne-meta">
        <strong>{n.author_name ?? "unknown"}</strong> · {formatDateTime(n.created_at)}
        {n.corrects_id && <> <Tag kind="mute">corrected</Tag></>}
        {n.deleted_at && <> <Tag kind="bad">deleted</Tag></>}
      </p>
      {n.deleted_at ? (
        <p className="muted">Deleted{n.deleted_by_name ? ` by ${n.deleted_by_name}` : ""} on {formatDateTime(n.deleted_at)}. It stays in the history.</p>
      ) : (
        <textarea className="ne-body" value={body} maxLength={20000} aria-label={`${noun} text`}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && changed) correct(); }} />
      )}
      <ErrorNote error={a.error} />
      <div className="ne-bar">
        {changed ? (
          <>
            <span className="muted small">Saving adds a corrected version; the original stays in the history.</span>
            <span className="row">
              <button className="quiet" onClick={() => setBody(n.body)}>Discard</button>
              <button className="primary" disabled={a.busy} onClick={correct}>Save correction</button>
            </span>
          </>
        ) : (
          <>
            <button className="link" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>
              <Icon name="history" size={15} /> {showHistory ? "Hide history" : "History"}
            </button>
            {!n.deleted_at && (confirmDelete ? (
              <span className="row">
                <span className="small">Mark as deleted? Nothing is erased.</span>
                <button className="quiet" onClick={() => setConfirmDelete(false)}>Cancel</button>
                <button className="danger" disabled={a.busy} onClick={remove}>Delete</button>
              </span>
            ) : (
              <button className="link" onClick={() => setConfirmDelete(true)}><Icon name="trash" size={15} /> Delete</button>
            ))}
          </>
        )}
      </div>
      {showHistory && (
        <div className="ne-history">
          <p className="eyebrow">History, oldest first</p>
          {!hist ? <Loading /> : (
            <ol>
              {hist.map((h) => (
                <li key={h.id} className={h.deleted_at ? "deleted" : ""}>
                  <span className="meta"><strong>{h.author_name ?? "unknown"}</strong> · {formatDateTime(h.created_at)}
                    {h.deleted_at && <> <Tag kind="bad">deleted {formatDateTime(h.deleted_at)}</Tag></>}</span>
                  <p className="pre">{h.body}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
