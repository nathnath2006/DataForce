import { useState } from "react";
import { useNavigate } from "react-router";
import { useWs } from "../context";
import { flowApi } from "../flows/flowApi";
import { themesVsWinRateGraph } from "../flows/graph";
import { AiBadge, Empty, ErrorNote, Field, Loading, Tag, useAction, useLoad } from "../ui";
import { meetingsApi } from "./api";
import { DeleteMeeting, MeetingTable, TranscriptDialog } from "./MeetingsPanel";
import { clampK, exactCount, formatDate } from "./text";
import type { DocumentOut, ThemeOut } from "./types";
import "./meetings.css";

const PAGE = 25;

export function MeetingsPage() {
  const { ws } = useWs();
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => meetingsApi.page(ws.slug, { limit: PAGE, offset }), [ws.slug, offset]);
  const [viewing, setViewing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  const total = list.data?.total ?? 0;
  return (
    <section className="stack">
      <h1>Meetings</h1>
      <ErrorNote error={list.error} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.items.length === 0 && <Empty>No transcript yet. Upload one from an account or company page.</Empty>}
      {list.data && list.data.items.length > 0 && (
        <div className="card stack">
          <MeetingTable docs={list.data.items} showAccount onView={setViewing} onDelete={setDeleting} />
          <div className="row pager">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <span className="muted small">{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>
        </div>
      )}
      {viewing && <TranscriptDialog id={viewing} onClose={() => setViewing(null)} />}
      {deleting && <DeleteMeeting doc={deleting} onClose={() => setDeleting(null)} onDone={list.reload} />}
      <ThemesSection onChanged={list.reload} />
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
          <label className="row"><input type="checkbox" checked={useAi} onChange={(ev) => setUseAi(ev.target.checked)} /> Use AI to name themes</label>
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
            Run of {new Date(r.created_at).toLocaleString()}: k={r.k}, {exactCount(r.n_chunks_used, "passage")} used,
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
