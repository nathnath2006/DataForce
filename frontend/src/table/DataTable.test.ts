import { describe, expect, it, vi } from "vitest";
import { createElement as h, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { DataTable, nextSort, type Column } from "./DataTable";

interface R { id: string; name: string; amount: number }
const cols: Column<R>[] = [
  { key: "name", header: "Name", cell: (r) => r.name, sortable: true },
  { key: "amount", header: "Amount", cell: (r) => r.amount, numeric: true, sortable: true },
];
const rows: R[] = [{ id: "1", name: "Acme", amount: 5 }];
const html = (el: ReactElement) => renderToStaticMarkup(h(MemoryRouter, null, el));

describe("DataTable", () => {
  it("renders rows, links the first cell and right-aligns numbers", () => {
    const out = html(h(DataTable<R>, { columns: cols, rows, rowKey: (r) => r.id, rowHref: (r) => `/x/${r.id}` }));
    expect(out).toContain('href="/x/1"');
    expect(out).toContain('class="num"');
  });
  it("shows empty and loading states", () => {
    expect(html(h(DataTable<R>, { columns: cols, rows: [], rowKey: (r) => r.id, empty: "No deals" }))).toContain("No deals");
    expect(html(h(DataTable<R>, { columns: cols, rows: [], rowKey: (r) => r.id, loading: true }))).toContain("Loading");
  });
  it("marks the sorted column and dense mode", () => {
    const out = html(h(DataTable<R>, { columns: cols, rows, rowKey: (r) => r.id, sort: { key: "amount", dir: "desc" }, onSort: vi.fn(), dense: true }));
    expect(out).toContain('aria-sort="descending"');
    expect(out).toContain("dense");
  });
  it("cycles the sort", () => {
    expect(nextSort(null, "a")).toEqual({ key: "a", dir: "asc" });
    expect(nextSort({ key: "a", dir: "asc" }, "a")).toEqual({ key: "a", dir: "desc" });
    expect(nextSort({ key: "a", dir: "desc" }, "b")).toEqual({ key: "b", dir: "asc" });
  });
});
