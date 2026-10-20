import { Link } from "react-router";
import { activityApi } from "../activity/api";
import type { TaskOut } from "../activity/types";
import { useSeesAll } from "../auth";
import { useWs } from "../context";
import { formatDate, label } from "../lib";
import { DataTable, type Column } from "../table/DataTable";
import { Pager } from "../table/Pager";
import { useListQuery } from "../table/useListQuery";
import { ErrorNote, Tag, useAction } from "../ui";
import "../home/home.css";

const STATUSES = ["open", "suggested", "done", "dismissed"] as const;
const DUES = [["overdue", "Overdue"], ["this_week", "This week"], ["later", "Later"], ["none", "No date"]] as const;
const KIND = { open: undefined, suggested: "warn", done: "ok", dismissed: "mute" } as const;

export function TasksPage() {
  const { ws, users } = useWs();
  const seesAll = useSeesAll();
  const act = useAction();
  const list = useListQuery<TaskOut>({
    resource: "tasks", filters: ["status", "due", "owner_id"],
    // Open tasks by default; "all" lifts the filter.
    fetch: (p, signal) => activityApi.tasksPage(ws.slug, { ...p, status: p.status === "" ? "open" : p.status === "all" ? undefined : p.status }, signal),
  });
  const { data, reload } = list;
  const run = (fn: () => Promise<unknown>) => void act.run(async () => { await fn(); reload(); });
  const columns: Column<TaskOut>[] = [
    { key: "title", header: "Task", sortable: true, cell: (t) => t.title },
    { key: "deal", header: "Deal", cell: (t) => (t.deal_id
      ? <Link to={`/w/${ws.slug}/deals/${t.deal_id}`}>{t.deal_name ?? "Deal"}</Link>
      : t.account_id ? <Link to={`/w/${ws.slug}/accounts/${t.account_id}`}>{t.account_name ?? "Account"}</Link> : "—") },
    { key: "due_on", header: "Due", sortable: true, cell: (t) => formatDate(t.due_on) },
    { key: "status", header: "Status", sortable: true, cell: (t) => <Tag kind={KIND[t.status]}>{label(t.status)}</Tag> },
    { key: "owner", header: "Owner", cell: (t) => t.owner_name ?? "—" },
    { key: "actions", header: "", cell: (t) => (
      <span className="row-actions">
        {t.status === "open" && <button type="button" onClick={() => run(() => activityApi.updateTask(ws.slug, t.id, { status: "done" }))}>Complete</button>}
        {t.status === "suggested" && <button type="button" onClick={() => run(() => activityApi.acceptTask(ws.slug, t.id))}>Accept</button>}
        {(t.status === "open" || t.status === "suggested") && <button type="button" onClick={() => run(() => activityApi.updateTask(ws.slug, t.id, { status: "dismissed" }))}>Dismiss</button>}
        {(t.status === "done" || t.status === "dismissed") && <button type="button" onClick={() => run(() => activityApi.updateTask(ws.slug, t.id, { status: "open" }))}>Reopen</button>}
      </span>
    ) },
  ];
  return (
    <section>
      <div className="page-title"><h1>Tasks</h1></div>
      <div className="row wrap filters">
        <select aria-label="Status" value={list.f("status") || "open"} onChange={(e) => list.setFilter("status", e.target.value)}>
          {STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          <option value="all">All statuses</option>
        </select>
        <select aria-label="Due" value={list.f("due")} onChange={(e) => list.setFilter("due", e.target.value)}>
          <option value="">Any due date</option>{DUES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {seesAll && (
          <select aria-label="Owner" value={list.f("owner_id")} onChange={(e) => list.setFilter("owner_id", e.target.value)}>
            <option value="">All owners</option>{users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        )}
      </div>
      <ErrorNote error={list.error} /><ErrorNote error={act.error} />
      <DataTable columns={columns} rows={data?.items ?? []} rowKey={(t) => t.id} sort={list.sort} onSort={list.setSort}
        loading={list.loading} caption="Tasks" empty="No task matches." />
      {data && <Pager offset={data.offset} limit={data.limit} shown={data.items.length} total={data.total} onOffset={list.setOffset} />}
    </section>
  );
}
