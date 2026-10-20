import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useCanDelete } from "../auth";
import { DataTable, type Column } from "../table/DataTable";
import { Pager } from "../table/Pager";
import { useListQuery, useUrlSearch } from "../table/useListQuery";
import { useWs } from "../context";
import { flowApi } from "../flows/flowApi";
import { themesVsWinRateGraph } from "../flows/graph";
import { AiBadge, Empty, ErrorNote, Field, Loading, Tag, useAction, useLoad } from "../ui";
import { meetingsApi } from "./api";
import { DeleteMeeting, TranscriptDialog } from "./MeetingsPanel";
import { formatDate, formatDateTime } from "../lib";
import { clampK, exactCount, speakerNames } from "./text";
import type { DocumentOut, ThemeOut } from "./types";
import { loadAllMeetings } from "./all";
import { MeetingsCalendar } from "./Calendar";
import "./meetings.css";

export function MeetingsPage() {
  const { ws } = useWs();
  const mayDelete = useCanDelete();
  const [mode, setMode] = useState<"calendar" | "list">("calendar");
  const all = useLoad(() => loadAllMeetings(ws.slug), [ws.slug]);
  const list = useListQuery<DocumentOut>({
    resource: "documents", filters: ["q"], defaultSort: { key: "meeting_date", dir: "desc" },
    fetch: (p, signal) => meetingsApi.page(ws.slug, p as { limit: number; offset: number }, signal),
  });
  const [text, setText] = useUrlSearch(list.f("q"), (v) => list.setFilter("q", v, true));
  const [viewing, setViewing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  const reload = () => { all.reload(); list.reload(); };
  const columns: Column<DocumentOut>[] = [
    { key: "meeting_date", header: "Date", sortable: true, cell: (d) => formatDate(d.meeting_date) },
    { key: "title", header: "Title", sortable: true, cell: (d) => <>{d.title}{d.deal_id && <> <Tag kind="mute">deal</Tag></>}</> },
    { key: "account", header: "Account", cell: (d) => <Link to={`/w/${ws.slug}/accounts/${d.account_id}`}>{d.account_name}</Link> },
    { key: "speakers", header: "Speakers", cell: (d) => <span className="small">{speakerNames(d.speakers) || "—"}</span> },
    { key: "themes", header: "Themes", cell: (d) => <>{d.theme_labels.map((l) => <span key={l} className="chip">{l}</span>)}</> },
    { key: "actions", header: "", cell: (d) => (
      <span className="row end">
        <button onClick={() => setViewing(d.id)}>View</button>
        {mayDelete(null) && <button className="danger" onClick={() => setDeleting(d)}>Delete</button>}
      </span>
    ) },
  ];
  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>Meetings</h1>
          <p className="muted">{all.data ? exactCount(all.data.total, "meeting") : "…"}. Upload transcripts from an account or a company page.</p>
        </div>
        <div className="seg" role="group" aria-label="View">
          <button aria-pressed={mode === "calendar"} onClick={() => setMode("calendar")}>Calendar</button>
          <button aria-pressed={mode === "list"} onClick={() => setMode("list")}>List</button>
        </div>
      </div>
      <ErrorNote error={mode === "calendar" ? all.error : list.error} />
      {mode === "calendar" && (all.loading && !all.data ? <Loading /> : all.data && (
        <MeetingsCalendar docs={all.data.items} onView={setViewing} />
      ))}
      {mode === "list" && (
        <>
          <div className="row wrap filters">
            <input type="search" placeholder="Search title" aria-label="Search" value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <DataTable columns={columns} rows={list.data?.items ?? []} rowKey={(d) => d.id} sort={list.sort} onSort={list.setSort}
            loading={list.loading} caption="Meetings" empty="No transcript yet. Upload one from an account or company page." />
          {list.data && <Pager offset={list.data.offset} limit={list.data.limit} shown={list.data.items.length} total={list.data.total} onOffset={list.setOffset} />}
        </>
      )}
      {viewing && <TranscriptDialog id={viewing} onClose={() => setViewing(null)} />}
      {deleting && <DeleteMeeting doc={deleting} onClose={() => setDeleting(null)} onDone={reload} />}
      <ThemesSection onChanged={reload} />
    </section>
  );
}

function ThemesSection({ onChanged }: { onChanged: () => void }) {
  const { ws } = useWs();
  const latest = useLoad(() => meetingsApi.latestThemes(ws.slug), [ws.slug]);
  const [k, setK] = useState(8);
  const [useAi, setUseAi] = useState(true);
  const a = useAction();
  const run = () => void a.run(async () => {
    await meetingsApi.runThemes(ws.slug, { k: clampK(k), use_ai: useAi });
    latest.reload();
    onChanged();
  });
  const r = latest.data;
  return (
    <section className="stack">
      <h2>Themes</h2>
      <div className="card stack">
        <div className="row wrap">
          <Field label="Number of themes (2 to 30)">
            <input type="number" min={2} max={30} value={k} onChange={(ev) => setK(Number(ev.target.value))} />
          </Field>
          <label className="check"><input type="checkbox" checked={useAi} onChange={(ev) => setUseAi(ev.target.checked)} /> Use AI to name themes</label>
          <button className="primary" disabled={a.busy} onClick={run}>{a.busy ? "Finding…" : "Find themes"}</button>
        </div>
        <p className="muted small">
          {useAi
            ? "With AI, only each theme's top words and 3 short excerpts are sent to the model to propose a name. Full transcripts are never sent."
            : "Without AI, themes are named by their top words and nothing leaves this machine."}
        </p>
        <ErrorNote error={a.error} />
      </div>
      <ErrorNote error={latest.error} />
      {latest.loading && !r && <Loading />}
      {!latest.loading && !r && !latest.error && <Empty>No theme analysis yet.</Empty>}
      {r && (
        <>
          <p className="muted small">
            Run of {formatDateTime(r.created_at)}: k={r.k}, {exactCount(r.n_chunks_used, "passage")} used,
            {" "}{r.n_unassigned} unassigned{r.dropped_themes > 0 ? `, ${r.dropped_themes} too-small theme(s) dropped` : ""}.
          </p>
          <div className="themes-grid">{r.themes.map((t) => <ThemeCard key={t.id} theme={t} />)}</div>
        </>
      )}
    </section>
  );
}

function ThemeCard({ theme: t }: { theme: ThemeOut }) {
  const { ws } = useWs();
  const nav = useNavigate();
  const a = useAction();
  const test = () => void a.run(async () => {
    const f = await flowApi.create(ws.slug, {
      name: `Themes vs win rate (${t.label})`.slice(0, 200), graph: themesVsWinRateGraph(t.label),
    });
    nav(`/w/${ws.slug}/analysis/${f.id}`);
  });
  return (
    <article className="card stack">
      <div className="row between wrap">
        <h3>{t.label}</h3>
        <span className="row">
          <Tag>{t.kind}</Tag>
          {t.origin === "known" || t.named_by === "lexicon"
            ? <Tag kind="ok">known theme · found by keywords</Tag>
            : <Tag kind="mute">discovered topic</Tag>}
          {t.named_by === "llm" && <AiBadge>named by AI</AiBadge>}
        </span>
      </div>
      {t.description && <p>{t.description}</p>}
      <p className="small">
        <strong>{exactCount(t.n_chunks, "passage")}</strong>, <strong>{exactCount(t.n_documents, "meeting")}</strong>,{" "}
        <strong>{exactCount(t.n_accounts, "account")}</strong> <span className="muted">(exact count)</span>
      </p>
      <div>{t.top_terms.map((x) => <span key={x} className="chip">{x}</span>)}</div>
      {t.excerpts.map((x) => (
        <blockquote className="quote" key={x.chunk_id}>
          {x.text}
          <div className="muted small">{x.speaker ? `${x.speaker}, ` : ""}{x.account_name}, {formatDate(x.meeting_date)}</div>
        </blockquote>
      ))}
      <p className="muted small">
        {t.origin === "known" || t.named_by === "lexicon"
          ? "Found by matching sales keywords (French and English) in what customers said. A mention is not a cause: test it before drawing conclusions."
          : "Exploratory: a recurring topic in the remaining sentences. Topics describe, they do not prove."}
      </p>
      <ErrorNote error={a.error} />
      <div><button disabled={a.busy} onClick={test}>Test against win rate</button></div>
      <p className="muted small">
        A screening test, not proof: the theme was found in these same meetings, testing themes one
        by one raises the odds of a lucky result, and deals differ in how often (and with whom)
        they were met. Treat a "verified" difference as a lead to check.
      </p>
    </article>
  );
}
