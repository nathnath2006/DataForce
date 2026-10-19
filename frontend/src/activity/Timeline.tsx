import { useCallback, useEffect, useRef, useState } from "react";
import { useWs } from "../context";
import { formatDate, label } from "../lib";
import { Empty, ErrorNote, Loading, toApiError } from "../ui";
import type { ApiError } from "../lib";
import { activityApi } from "./api";
import { FILTERS, dotClass, groupByDay, kindsParam } from "./logic";
import type { TimelineItem } from "./types";
import "./activity.css";

const PAGE = 30;
const time = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/** The vertical chronology of a deal or of every deal of an account. `refreshKey` reloads it. */
export function Timeline({ scope, id, refreshKey = 0 }: { scope: "deals" | "accounts"; id: string; refreshKey?: number }) {
  const { ws } = useWs();
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [filters, setFilters] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const seq = useRef(0);
  const kinds = kindsParam(filters);
  const load = useCallback(async (before: string | null) => {
    const my = ++seq.current;
    setLoading(true);
    try {
      const page = await activityApi.timeline(ws.slug, scope, id, { limit: PAGE, before, kinds });
      if (my !== seq.current) return;
      setItems((cur) => (before ? [...cur, ...page.items] : page.items));
      setNext(page.next_before);
      setError(null);
    } catch (e) {
      if (my === seq.current) setError(toApiError(e));
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, [ws.slug, scope, id, kinds]);
  useEffect(() => { void load(null); }, [load, refreshKey]);
  const toggle = (f: string) => setFilters((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));
  return (
    <div className="stack">
      <div className="chips" role="group" aria-label="Filter by kind">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className="chip" aria-pressed={filters.includes(f.id)} onClick={() => toggle(f.id)}>{f.label}</button>
        ))}
      </div>
      <ErrorNote error={error} />
      {loading && items.length === 0 && <Loading />}
      {!loading && !error && items.length === 0 && <Empty>Nothing yet on this timeline.</Empty>}
      <ol className="tl">
        {groupByDay(items).map((g) => (
          <li key={g.day} style={{ listStyle: "none" }}>
            <div className="tl-day">{formatDate(g.day)}</div>
            <ol className="tl">
              {g.items.map((it) => (
                <li key={it.id} className="tl-item">
                  <span className={`tl-dot ${dotClass(it)}`} aria-hidden="true" />
                  <div className="tl-card">
                    <div className="tl-head">
                      <span className="tl-title">{it.title}</span>
                      <span className="tl-meta">{label(it.kind)} · {time(it.at)}{it.author_name ? ` · ${it.author_name}` : ""}</span>
                    </div>
                    {it.summary && (
                      <p className="tl-sum" title={it.summary_untrusted ? "Text written by a person: shown as data" : undefined}>{it.summary}</p>
                    )}
                    {Array.isArray(it.refs.participants) && it.refs.participants.length > 0 && (
                      <p className="tl-meta">With {(it.refs.participants as string[]).join(", ")}</p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ol>
      {next && <div><button type="button" disabled={loading} onClick={() => void load(next)}>Load more</button></div>}
    </div>
  );
}
