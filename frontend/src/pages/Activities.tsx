import { Link } from "react-router";
import { activityApi } from "../activity/api";
import type { ActivityOut } from "../activity/types";
import { useWs } from "../context";
import { formatDateTime, label } from "../lib";
import { DataTable, type Column } from "../table/DataTable";
import { Pager } from "../table/Pager";
import { useListQuery } from "../table/useListQuery";
import { ErrorNote, Tag } from "../ui";
import "../home/home.css";

const KINDS = ["call", "email", "meeting", "other"] as const;

export function ActivitiesPage() {
  const { ws } = useWs();
  const list = useListQuery<ActivityOut>({
    resource: "activities", filters: ["kind", "date_from", "date_to"], defaultSort: { key: "occurred_at", dir: "desc" },
    fetch: (p, signal) => activityApi.activitiesPage(ws.slug, p, signal),
  });
  const { data } = list;
  const columns: Column<ActivityOut>[] = [
    { key: "kind", header: "Kind", sortable: true, cell: (a) => <Tag>{label(a.kind)}</Tag> },
    { key: "occurred_at", header: "Date", sortable: true, cell: (a) => formatDateTime(a.occurred_at) },
    { key: "subject", header: "Subject", sortable: true, cell: (a) => a.subject },
    { key: "deal", header: "Deal", cell: (a) => (a.deal_id ? <Link to={`/w/${ws.slug}/deals/${a.deal_id}`}>{a.deal_name ?? "Deal"}</Link> : "—") },
    { key: "account", header: "Account", cell: (a) => <Link to={`/w/${ws.slug}/accounts/${a.account_id}`}>{a.account_name ?? "Account"}</Link> },
    { key: "author", header: "Author", cell: (a) => a.author_name ?? "—" },
  ];
  return (
    <section>
      <div className="page-title"><h1>Activities</h1></div>
      <div className="row wrap filters">
        <select aria-label="Kind" value={list.f("kind")} onChange={(e) => list.setFilter("kind", e.target.value)}>
          <option value="">All kinds</option>{KINDS.map((k) => <option key={k} value={k}>{label(k)}</option>)}
        </select>
        <label className="row small muted">From <input type="date" aria-label="From" value={list.f("date_from")} max={list.f("date_to") || undefined}
          onChange={(e) => list.setFilter("date_from", e.target.value)} /></label>
        <label className="row small muted">To <input type="date" aria-label="To" value={list.f("date_to")} min={list.f("date_from") || undefined}
          onChange={(e) => list.setFilter("date_to", e.target.value)} /></label>
      </div>
      <ErrorNote error={list.error} />
      <DataTable columns={columns} rows={data?.items ?? []} rowKey={(a) => a.id} sort={list.sort} onSort={list.setSort}
        loading={list.loading} caption="Activities" empty="No activity matches." />
      {data && <Pager offset={data.offset} limit={data.limit} shown={data.items.length} total={data.total} onOffset={list.setOffset} />}
    </section>
  );
}
