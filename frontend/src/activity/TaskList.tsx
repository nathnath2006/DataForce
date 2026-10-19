import { useState } from "react";
import { useWs } from "../context";
import { formatDate } from "../lib";
import { Empty, ErrorNote, Loading, useAction, useLoad } from "../ui";
import { activityApi } from "./api";
import "./activity.css";

/** Small task list with checkboxes (open tasks first). */
export function TaskList({ dealId, onChanged }: { dealId: string; onChanged?: () => void }) {
  const { ws, actingAs } = useWs();
  const list = useLoad(() => activityApi.listTasks(ws.slug, { deal_id: dealId }), [ws.slug, dealId]);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const act = useAction();
  const done = () => { list.reload(); onChanged?.(); };
  const add = async () => {
    const r = await act.run(() => activityApi.createTask(ws.slug, {
      title: title.trim(), deal_id: dealId, due_on: due || null, owner_id: actingAs,
    }));
    if (r) { setTitle(""); setDue(""); done(); }
  };
  return (
    <div className="stack">
      <ErrorNote error={list.error} />
      <ErrorNote error={act.error} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <Empty>No task on this deal.</Empty>}
      <ul className="tasklist">
        {list.data?.map((t) => (
          <li key={t.id}>
            {t.status === "suggested" ? (
              <>
                <span className="tag warn">Suggested</span>
                <span>{t.title}</span>
                <button type="button" onClick={() => void act.run(() => activityApi.acceptTask(ws.slug, t.id)).then(done)}>Accept</button>
                <button type="button" onClick={() => void act.run(() => activityApi.updateTask(ws.slug, t.id, { status: "dismissed" })).then(done)}>Dismiss</button>
              </>
            ) : (
              <label className="check">
                <input type="checkbox" checked={t.status === "done"} disabled={t.status === "dismissed" || act.busy}
                  onChange={(ev) => void act.run(() => activityApi.updateTask(ws.slug, t.id, { status: ev.target.checked ? "done" : "open" })).then(done)} />
                <span className={t.status === "done" || t.status === "dismissed" ? "done" : ""}>{t.title}</span>
              </label>
            )}
            {t.due_on && <span className="tl-meta">due {formatDate(t.due_on)}</span>}
            {t.owner_name && <span className="tl-meta">{t.owner_name}</span>}
          </li>
        ))}
      </ul>
      <form className="row wrap" onSubmit={(ev) => { ev.preventDefault(); void add(); }}>
        <input value={title} maxLength={300} placeholder="New task" aria-label="New task" onChange={(ev) => setTitle(ev.target.value)} />
        <input type="date" value={due} aria-label="Due date" onChange={(ev) => setDue(ev.target.value)} />
        <button type="submit" disabled={!title.trim() || act.busy}>Add</button>
      </form>
    </div>
  );
}
