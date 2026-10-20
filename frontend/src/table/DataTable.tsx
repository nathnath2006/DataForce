import type { ReactNode } from "react";
import { Link } from "react-router";
import "./table.css";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Right-aligned with tabular numbers. */
  numeric?: boolean;
  sortable?: boolean;
  width?: string;
}
export type SortDir = "asc" | "desc";
export interface SortState { key: string; dir: SortDir }

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** When set, the first cell of each row is a link to this path. */
  rowHref?: (row: T) => string;
  sort?: SortState | null;
  onSort?: (next: SortState) => void;
  dense?: boolean;
  loading?: boolean;
  empty?: ReactNode;
  caption?: string;
  maxHeight?: string;
}

/** Next sort state when a header is clicked: new column starts ascending, same column flips. */
export function nextSort(cur: SortState | null | undefined, key: string): SortState {
  return cur && cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" };
}

export function DataTable<T>(p: DataTableProps<T>) {
  const { columns } = p;
  const body = p.loading && p.rows.length === 0
    ? <tr><td className="muted dt-state" colSpan={columns.length}>Loading…</td></tr>
    : p.rows.length === 0
      ? <tr><td className="muted dt-state" colSpan={columns.length}>{p.empty ?? "Nothing to show."}</td></tr>
      : p.rows.map((r) => (
        <tr key={p.rowKey(r)}>
          {columns.map((c, i) => (
            <td key={c.key} className={c.numeric ? "num" : undefined}>
              {i === 0 && p.rowHref ? <Link to={p.rowHref(r)}>{c.cell(r)}</Link> : c.cell(r)}
            </td>
          ))}
        </tr>
      ));
  return (
    <div className="tablewrap dt-wrap" style={p.maxHeight ? { maxHeight: p.maxHeight } : undefined} aria-busy={p.loading || undefined}>
      <table className={`dt ${p.dense ? "dense" : ""}`}>
        {p.caption && <caption className="sr-only">{p.caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => {
              const on = p.sort?.key === c.key;
              const aria = on ? (p.sort!.dir === "asc" ? "ascending" : "descending") : c.sortable ? "none" : undefined;
              return (
                <th key={c.key} className={c.numeric ? "num" : undefined} style={c.width ? { width: c.width } : undefined} aria-sort={aria}>
                  {c.sortable && p.onSort ? (
                    <button type="button" className="dt-sort" onClick={() => p.onSort!(nextSort(p.sort, c.key))}>
                      {c.header}<span aria-hidden="true">{on ? (p.sort!.dir === "asc" ? "↑" : "↓") : ""}</span>
                    </button>
                  ) : c.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  );
}
