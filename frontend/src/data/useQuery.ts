import { useCallback, useEffect, useRef, useState } from "react";
import { q, w } from "../api";
import { toApiError } from "../ui";
import type { ApiError } from "../lib";
import { cacheGet, cacheSet, invalidate, isFresh, onInvalidate } from "./cache";

export { invalidate };

/** Cache key of a list endpoint: the same string the request goes to, so `invalidate("/w/acme/deals")` works. */
export function listKey(ws: string, resource: string, params: Record<string, string | number | undefined | null> = {}): string {
  return `${w(ws)}/${resource}${q(params)}`;
}

export interface QueryResult<R> {
  data: R | null;
  error: ApiError | null;
  /** True while there is nothing to show yet (first load of this key). */
  loading: boolean;
  /** True while a request is in flight, including a background revalidation. */
  fetching: boolean;
  reload: () => void;
}

/**
 * Fetch `fetcher(signal)` for `key` (null disables). Cached by key: cached data shows at once, and is
 * refetched in the background unless younger than 30 s (stale-while-revalidate). The request is aborted
 * when the key changes or the component unmounts. `invalidate(prefix)` refetches matching mounted queries.
 */
export function useQuery<R>(key: string | null, fetcher: (signal: AbortSignal) => Promise<R>): QueryResult<R> {
  const cached = key ? (cacheGet(key)?.data as R | undefined) : undefined;
  const [state, setState] = useState<{ key: string | null; data: R | null; error: ApiError | null }>(
    { key, data: cached ?? null, error: null });
  const [fetching, setFetching] = useState(false);
  const [n, setN] = useState(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  useEffect(() => {
    if (!key) return;
    return onInvalidate((prefix) => { if (key.startsWith(prefix)) setN((x) => x + 1); });
  }, [key]);

  useEffect(() => {
    if (!key) { setState({ key, data: null, error: null }); return; }
    const hit = cacheGet(key);
    setState((s) => (s.key === key ? s : { key, data: (hit?.data as R | undefined) ?? null, error: null }));
    if (n === 0 && isFresh(hit)) return;
    const ac = new AbortController();
    setFetching(true);
    fetchRef.current(ac.signal).then(
      (d) => {
        if (ac.signal.aborted) return;
        cacheSet(key, d);
        setState({ key, data: d, error: null });
        setFetching(false);
      },
      (e: unknown) => {
        if (ac.signal.aborted) return;
        setState((s) => ({ key, data: s.key === key ? s.data : null, error: toApiError(e) }));
        setFetching(false);
      },
    );
    return () => { ac.abort(); };
  }, [key, n]);

  const reload = useCallback(() => setN((x) => x + 1), []);
  // Never show data of another key (a render can run before the effect swaps the state).
  const data = state.key === key ? state.data : ((key ? (cacheGet(key)?.data as R | undefined) : undefined) ?? null);
  return { data, error: state.key === key ? state.error : null, loading: !!key && data === null && state.error === null, fetching, reload };
}
