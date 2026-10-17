import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useWs } from "../context";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Tag, emptyToNull, useAction, useLoad } from "../ui";
import { meetingsApi } from "./api";
import { buildTurns, formatDate, legend, speakerNames } from "./text";
import type { DocumentOut } from "./types";
import "./meetings.css";

type Scope = { kind: "account" | "company"; id: string };

export function MeetingsPanel({ scope }: { scope: Scope }) {
  const { ws } = useWs();
  const list = useLoad(
    () => (scope.kind === "account" ? meetingsApi.forAccount(ws.slug, scope.id) : meetingsApi.forCompany(ws.slug, scope.id)),
    [ws.slug, scope.kind, scope.id],
  );
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  return (
    <section className="card stack">
      <div className="row between wrap">
        <h2>Meetings</h2>
        <button onClick={() => setUploading(true)}>Upload transcript</button>
      </div>
      <ErrorNote error={list.error} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.length === 0 && <Empty>No transcript yet. Upload a .pdf, .md or .txt file.</Empty>}
      {list.data && list.data.length > 0 && (
        <MeetingTable docs={list.data} showAccount={scope.kind === "company"} onView={setViewing} onDelete={setDeleting} />
      )}
      {uploading && (
        <UploadDialog scope={scope} onClose={() => setUploading(false)} onDone={() => { setUploading(false); list.reload(); }} />
      )}
      {viewing && <TranscriptDialog id={viewing} onClose={() => setViewing(null)} />}
      {deleting && <DeleteMeeting doc={deleting} onClose={() => setDeleting(null)} onDone={list.reload} />}
    </section>
  );
}

export function MeetingTable(props: {
  docs: DocumentOut[]; showAccount: boolean; onView: (id: string) => void; onDelete: (d: DocumentOut) => void;
}) {
  const { ws } = useWs();
  return (
    <div className="tablewrap"><table>
      <thead><tr><th>Date</th><th>Title</th>{props.showAccount && <th>Account</th>}<th>Speakers</th><th>Themes</th><th /></tr></thead>
      <tbody>{props.docs.map((d) => (
        <tr key={d.id}>
          <td>{formatDate(d.meeting_date)}</td>
          <td>{d.title}{d.deal_id && <> <Tag kind="mute">deal</Tag></>}</td>
          {props.showAccount && <td><Link to={`/w/${ws.slug}/accounts/${d.account_id}`}>{d.account_name}</Link></td>}
          <td className="small">{speakerNames(d.speakers) || "—"}</td>
          <td>{d.theme_labels.map((l) => <span key={l} className="chip">{l}</span>)}</td>
          <td className="row end">
            <button onClick={() => props.onView(d.id)}>View</button>
            <button className="danger" onClick={() => props.onDelete(d)}>Delete</button>
          </td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

export function DeleteMeeting(props: { doc: DocumentOut; onClose: () => void; onDone: () => void }) {
  const { ws } = useWs();
  return (
    <Confirm title="Delete transcript" confirmLabel="Delete" danger onClose={props.onClose}
      onConfirm={async () => { await meetingsApi.remove(ws.slug, props.doc.id); props.onDone(); }}>
      <p>Delete <strong>{props.doc.title}</strong>? The imported text is the only copy and cannot be recovered.</p>
    </Confirm>
  );
}

const TURNS_PAGE = 200;
// The server refuses larger files (TRANSCRIPT_MAX_BYTES); checking here avoids a pointless upload.
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export function TranscriptDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { ws } = useWs();
  const doc = useLoad(() => meetingsApi.get(ws.slug, id), [ws.slug, id]);
  const d = doc.data;
  // Built once per document; long transcripts are shown in pages of turns (SR13-01).
  const turns = useMemo(() => (d ? buildTurns(d.text, d.chunks, d.chunk_themes) : []), [d]);
  const [shown, setShown] = useState(TURNS_PAGE);
  const leg = d ? legend(d.chunk_themes) : [];
  const cls = new Map(leg.map((l) => [l.id, l.cls]));
  return (
    <Modal title={d ? d.title : "Transcript"} onClose={onClose} wide>
      <div className="stack">
        <ErrorNote error={doc.error} />
        {doc.loading && !d && <Loading />}
        {d && (
          <>
            <div className="muted small">{formatDate(d.meeting_date)} · {d.account_name} · {d.n_chars.toLocaleString("en-IE")} characters</div>
            {leg.length > 0 && (
              <div className="row wrap" aria-label="Legend">
                {leg.map((l) => <span key={l.id} className={`swatch ${l.cls}`}>{l.label}</span>)}
              </div>
            )}
            <div className="transcript">
              {turns.slice(0, shown).map((t, i) => (
                <div className="turn" key={i}>
                  {t.speaker && <span className="who">{t.speaker}</span>}
                  <p className="says">{t.segs.map((s, j) => (
                    s.themeId ? <mark key={j} className={cls.get(s.themeId) ?? "th0"} title={s.label ?? undefined}>{s.text}</mark>
                      : <span key={j}>{s.text}</span>
                  ))}</p>
                </div>
              ))}
            </div>
            {turns.length > shown && (
              <button onClick={() => setShown((n) => n + TURNS_PAGE)}>
                Show more ({turns.length - shown} more turns)
              </button>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function UploadDialog(props: { scope: Scope; onClose: () => void; onDone: () => void }) {
  const { ws } = useWs();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [accountId, setAccountId] = useState(props.scope.kind === "account" ? props.scope.id : "");
  const [dealId, setDealId] = useState("");
  const accounts = useLoad(
    async () => (props.scope.kind === "company" ? meetingsApi.companyAccounts(ws.slug, props.scope.id) : []),
    [ws.slug, props.scope.kind, props.scope.id],
  );
  const deals = useLoad(
    async () => (accountId ? meetingsApi.accountDeals(ws.slug, accountId) : []),
    [ws.slug, accountId],
  );
  const a = useAction();
  const submit = () => void a.run(async () => {
    if (!file || !accountId) return;
    await meetingsApi.upload(ws.slug, accountId, {
      file, title: emptyToNull(title) ?? undefined, meeting_date: emptyToNull(date) ?? undefined,
      deal_id: dealId || undefined,
    });
    props.onDone();
  });
  return (
    <Modal title="Upload transcript" onClose={props.onClose}>
      <div className="stack">
        {props.scope.kind === "company" && (
          <Field label="Account">
            <select value={accountId} onChange={(ev) => { setAccountId(ev.target.value); setDealId(""); }}>
              <option value="">Choose an account</option>
              {(accounts.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="File (.pdf, .md, .txt)">
          <input type="file" accept=".pdf,.md,.markdown,.txt" onChange={(ev) => setFile(ev.target.files?.[0] ?? null)} />
        </Field>
        {file && file.size > MAX_UPLOAD_BYTES && (
          <div className="note warn" role="alert">This file is larger than 5 MB: the server will refuse it.</div>
        )}
        <Field label="Title (optional)"><input value={title} maxLength={200} onChange={(ev) => setTitle(ev.target.value)} /></Field>
        <Field label="Meeting date (optional)"><input type="date" value={date} onChange={(ev) => setDate(ev.target.value)} /></Field>
        <Field label="Deal (optional)">
          <select value={dealId} onChange={(ev) => setDealId(ev.target.value)} disabled={!accountId}>
            <option value="">No deal</option>
            {(deals.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </Field>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy || !file || !accountId || (file?.size ?? 0) > MAX_UPLOAD_BYTES} onClick={submit}>Upload</button>
        </div>
      </div>
    </Modal>
  );
}
