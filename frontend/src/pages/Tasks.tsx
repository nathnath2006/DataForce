import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";
import { Link } from "react-router";
import { activityApi } from "../activity/api";
import type { TaskOut, TaskStatus } from "../activity/types";
import { useSeesAll } from "../auth";
import { useWs } from "../context";
import { formatDate } from "../lib";
import { COLUMNS, computeStats, dueTone, groupByColumn, initial, moveTarget, withStatus } from "../tasks/board";
import { ErrorNote, useAction } from "../ui";
import { AccountPicker } from "../ui/pickers";
import "../home/home.css";
import "../tasks/tasks.css";

const Dots = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="currentColor">
    {[3, 7, 11].flatMap((y) => [4.5, 9.5].map((x) => <circle key={`${x}${y}`} cx={x} cy={y} r="1.1" />))}
  </svg>
);
const Chev = ({ dir }: { dir: "l" | "r" }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={dir === "l" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"} />
  </svg>
);

export function TasksPage() {
  const { ws, users } = useWs();
  const seesAll = useSeesAll();
  const act = useAction();
  const [tasks, setTasks] = useState<TaskOut[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [owner, setOwner] = useState("");
  const [showDismissed, setShowDismissed] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    activityApi.tasksPage(ws.slug, { limit: 200, owner_id: owner || undefined })
      .then((r) => { setTasks(r.items); setLoadError(null); }, (e) => setLoadError(e));
  }, [ws.slug, owner]);
  useEffect(() => { load(); }, [load]);

  const live = useMemo(() => (tasks ?? []).filter((t) => t.status !== "dismissed"), [tasks]);
  const groups = useMemo(() => groupByColumn(tasks ?? []), [tasks]);
  const dismissed = useMemo(() => (tasks ?? []).filter((t) => t.status === "dismissed"), [tasks]);
  const stats = useMemo(() => computeStats(tasks ?? []), [tasks]);

  /** Optimistic move with rollback on error. */
  const move = (t: TaskOut, to: TaskStatus) => {
    if (t.status === to || !tasks) return;
    const before = tasks;
    setTasks(withStatus(tasks, t.id, to));
    void act.run(async () => {
      try {
        if (t.status === "suggested" && to === "open") await activityApi.acceptTask(ws.slug, t.id);
        else await activityApi.updateTask(ws.slug, t.id, { status: to });
      } catch (e) { setTasks(before); throw e; }
    });
  };
  const onDrop = (ev: DragEvent, to: TaskStatus) => {
    ev.preventDefault();
    const t = tasks?.find((x) => x.id === (dragId ?? ev.dataTransfer.getData("text/plain")));
    setDragId(null); setOverCol(null);
    if (t) move(t, to);
  };

  const card = (t: TaskOut) => {
    const tone = dueTone(t.due_on, t.status);
    const left = moveTarget(t.status, -1), right = moveTarget(t.status, 1);
    const ref = t.deal_id
      ? <Link to={`/w/${ws.slug}/deals/${t.deal_id}`}>{t.deal_name ?? "Deal"}</Link>
      : t.account_id ? <Link to={`/w/${ws.slug}/accounts/${t.account_id}`}>{t.account_name ?? "Account"}</Link>
      : <span>No account</span>;
    return (
      <li key={t.id} className={`kb-card${dragId === t.id ? " dragging" : ""}`} draggable
        onDragStart={(e) => { setDragId(t.id); e.dataTransfer.setData("text/plain", t.id); e.dataTransfer.effectAllowed = "move"; }}
        onDragEnd={() => { setDragId(null); setOverCol(null); }}>
        <div className="kb-top"><span className="kb-ref">{ref}</span><span className="kb-grip" aria-hidden="true"><Dots /></span></div>
        <div className="kb-title">{t.title}</div>
        <div className="kb-chips">
          {t.due_on && <span className={`kb-chip ${tone}`}>{tone === "today" ? "Due today" : tone === "overdue" ? `Overdue ${formatDate(t.due_on)}` : formatDate(t.due_on)}</span>}
          <span className="kb-avatar" title={t.owner_name ?? "Unassigned"} aria-label={`Owner: ${t.owner_name ?? "unassigned"}`}>{initial(t.owner_name)}</span>
        </div>
        <div className="kb-actions">
          <span className="kb-txts">
          {t.status === "suggested" && <button type="button" className="kb-txt" onClick={() => move(t, "open")}>Accept</button>}
          {(t.status === "suggested" || t.status === "open") && <button type="button" className="kb-txt" onClick={() => move(t, "dismissed")}>Dismiss</button>}
          {t.status === "dismissed" && <button type="button" className="kb-txt" onClick={() => move(t, "open")}>Reopen</button>}
          </span>
          {t.status !== "dismissed" && <span className="kb-arrows">
            <button type="button" className="kb-arrow" disabled={!left} aria-label={`Move "${t.title}" left`} onClick={() => left && move(t, left)}><Chev dir="l" /></button>
            <button type="button" className="kb-arrow" disabled={!right} aria-label={`Move "${t.title}" right`} onClick={() => right && move(t, right)}><Chev dir="r" /></button>
          </span>}
        </div>
      </li>
    );
  };

  return (
    <section className="kb">
      <div className="page-title"><h1>Tasks</h1></div>
      <p className="muted">{live.length} tasks. Drag on a wide screen, or use the arrows on a card to move it one column at a time.</p>
      <div className="bento kb-stats">
        <div className="tile w3"><span className="muted">Open</span><strong className="kb-num">{stats.open}</strong></div>
        <div className="tile w3"><span className="muted">Overdue</span><strong className={`kb-num${stats.overdue > 0 ? " bad" : ""}`}>{stats.overdue}</strong></div>
        <div className="tile w3"><span className="muted">Due this week</span><strong className="kb-num">{stats.dueThisWeek}</strong></div>
        <div className="tile w3"><span className="muted">Done this week</span><strong className="kb-num">{stats.doneThisWeek}</strong></div>
        <div className="tile w12 kb-person">
          <span className="muted">By person (open)</span>
          {stats.byPerson.length === 0 ? <span className="muted">Nobody yet.</span> : (
            <ul>{stats.byPerson.map((p) => <li key={p.name}><span className="kb-avatar sm">{initial(p.name)}</span>{p.name}<strong>{p.open}</strong></li>)}</ul>
          )}
        </div>
      </div>
      <div className="kb-filters">
        {seesAll && (
          <select aria-label="Owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">All owners</option>{users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        )}
        <label className="kb-check"><input type="checkbox" checked={showDismissed} onChange={(e) => setShowDismissed(e.target.checked)} /> Show dismissed</label>
      </div>
      <ErrorNote error={loadError as never} /><ErrorNote error={act.error} />
      {tasks === null ? <p className="muted">Loading…</p> : (
        <div className="kb-board">
          {[...COLUMNS, ...(showDismissed ? [{ status: "dismissed", title: "Dismissed" } as const] : [])].map((c) => {
            const items = c.status === "dismissed" ? dismissed : groups[c.status];
            return (
              <div key={c.status} className={`kb-col${overCol === c.status ? " over" : ""}`} role="group" aria-label={c.title}
                onDragOver={(e) => { if (dragId) { e.preventDefault(); setOverCol(c.status); } }}
                onDragLeave={() => setOverCol((o) => (o === c.status ? null : o))}
                onDrop={(e) => onDrop(e, c.status)}>
                <h2>{c.title} <span className="muted">{items.length}</span></h2>
                <ul>{items.map(card)}</ul>
                {c.status === "open" && (adding
                  ? <AddTask onDone={() => { setAdding(false); load(); }} onCancel={() => setAdding(false)} />
                  : <button type="button" className="kb-add" onClick={() => setAdding(true)}>+ Add task</button>)}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function AddTask({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { ws } = useWs();
  const a = useAction();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [account, setAccount] = useState("");
  const submit = () => {
    if (!title.trim() || a.busy) return;
    void a.run(async () => {
      await activityApi.createTask(ws.slug, { title: title.trim(), due_on: due || null, account_id: account || null });
      onDone();
    });
  };
  return (
    <form className="kb-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <input aria-label="Task title" placeholder="Task title" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus required maxLength={300} />
      <input aria-label="Due date" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      <AccountPicker id={account} onChange={(id) => setAccount(id)} ariaLabel="Account (optional)" />
      <ErrorNote error={a.error} />
      <div className="row"><button className="primary" disabled={a.busy || !title.trim()}>Add</button><button type="button" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}
