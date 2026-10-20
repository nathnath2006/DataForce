import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useWs } from "../context";
import { listKey, useQuery } from "../data/useQuery";
import type { Page } from "../types";
import type { SortState } from "./DataTable";

export const PAGE_SIZE = 50;
type Params = Record<string, string | number | undefined>;

/**
 * A server-paged list whose page, sort and filters live in the URL query (`?page=2&sort=name&dir=desc&q=...`),
 * so back, forward and shared links work. Filters are sent to the server as given; `defaultSort` is only
 * what the server already does when no sort is sent (used to draw the header arrow).
 */
export function useListQuery<I>(o: {
  resource: string;
  filters: readonly string[];
  defaultSort?: SortState;
  fetch: (p: Params, signal: AbortSignal) => Promise<Page<I>>;
  /** False skips the request (the page shows something else). */
  enabled?: (filters: Record<string, string>) => boolean;
}) {
  const { ws } = useWs();
  const [sp, setSp] = useSearchParams();
  const page = Math.max(1, parseInt(sp.get("page") ?? "1", 10) || 1);
  const sortKey = sp.get("sort");
  const sortDir = sp.get("dir") === "desc" ? "desc" : "asc";
  const filters: Record<string, string> = {};
  for (const f of o.filters) filters[f] = sp.get(f) ?? "";
  const f = (k: string) => filters[k] ?? "";

  const offset = (page - 1) * PAGE_SIZE;
  const params: Params = { ...filters, limit: PAGE_SIZE, offset };
  if (sortKey) { params.sort = sortKey; params.dir = sortDir; }
  const query = useQuery(o.enabled && !o.enabled(filters) ? null : listKey(ws.slug, o.resource, params), (signal) => o.fetch(params, signal));

  const update = useCallback((patch: Record<string, string | number | null>, replace = false) => {
    setSp((prev) => {
      const n = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === "") n.delete(k); else n.set(k, String(v));
      }
      if (!("page" in patch)) n.delete("page"); // any filter or sort change goes back to page 1
      return n;
    }, { replace });
  }, [setSp]);

  const sort: SortState | null = sortKey ? { key: sortKey, dir: sortDir } : (o.defaultSort ?? null);
  return {
    ...query, filters, f, sort, offset,
    setFilter: (k: string, v: string, replace = false) => update({ [k]: v }, replace),
    setSort: (s: SortState) => update({ sort: s.key, dir: s.dir }),
    setOffset: (off: number) => update({ page: off / PAGE_SIZE + 1 }),
  };
}

/** A text input state that commits to the URL (replace, no history spam) 300 ms after typing stops. */
export function useUrlSearch(value: string, commit: (v: string) => void) {
  const [text, setText] = useState(value);
  const commitRef = useRef(commit);
  commitRef.current = commit;
  useEffect(() => { setText(value); }, [value]); // back/forward changed the URL
  useEffect(() => {
    if (text.trim() === value) return;
    const t = setTimeout(() => commitRef.current(text.trim()), 300);
    return () => clearTimeout(t);
  }, [text, value]);
  return [text, setText] as const;
}
