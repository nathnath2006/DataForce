import { useState } from "react";
import { ErrorNote, Empty, Loading, Tag, useAction, useDebounced, useLoad } from "../ui";
import { formatDateTime } from "../lib";
import { mailboxApi } from "./api";
import type { MailboxMessageOut } from "./types";
import "./mailbox.css";

function Mail({ m, children }: { m: MailboxMessageOut; children?: React.ReactNode }) {
  // Everything below is plain text: React escapes it, nothing is injected as HTML.
  return (
    <li className="mb-mail">
      <div className="mb-mail-head">
        <span className="mb-subject">{m.subject}</span>
        <span className="mb-meta">{formatDateTime(m.sent_at)}</span>
      </div>
      <div className="mb-meta">From {m.from_addr}{m.to_addrs.length > 0 && <> · to {m.to_addrs.slice(0, 3).join(", ")}{m.to_addrs.length > 3 ? "…" : ""}</>}</div>
      {m.snippet && <p className="mb-snippet">{m.snippet}</p>}
      {m.reasons.length > 0 && m.suggested_deal_id && (
        <ul className="mb-reasons" aria-label="Why this email is suggested">
          {m.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      {children}
    </li>
  );
}

/** Emails suggested for a deal, with Link / Ignore, and "Find an email" to link any candidate by hand.
 *  Linked emails appear in the deal's timeline as activities; `onLinked` lets the page reload it. */
export function DealEmailsPanel({ ws, dealId, onLinked }: { ws: string; dealId: string; onLinked?: () => void }) {
  const suggested = useLoad(() => mailboxApi.messages(ws, { deal_id: dealId, limit: 20 }), [ws, dealId]);
  const [finding, setFinding] = useState(false);
  const [term, setTerm] = useState("");
  const debounced = useDebounced(term.trim());
  const found = useLoad(
    () => (finding ? mailboxApi.messages(ws, { q: debounced || undefined, limit: 20 }) : Promise.resolve([] as MailboxMessageOut[])),
    [ws, finding, debounced],
  );
  const act = useAction();

  const link = (m: MailboxMessageOut) => act.run(async () => {
    await mailboxApi.link(ws, m.id, dealId);
    suggested.reload(); found.reload(); onLinked?.();
  });
  const ignore = (m: MailboxMessageOut) => act.run(async () => {
    await mailboxApi.ignore(ws, m.id);
    suggested.reload(); found.reload();
  });
  const actions = (m: MailboxMessageOut) => (
    <div className="mb-actions">
      {m.state === "linked" ? <Tag kind="ok">linked</Tag> : (
        <>
          <button className="primary" disabled={act.busy} onClick={() => void link(m)}>Link to this deal</button>
          {m.state !== "ignored" && <button disabled={act.busy} onClick={() => void ignore(m)}>Ignore</button>}
          {m.state === "ignored" && <Tag kind="mute">ignored</Tag>}
        </>
      )}
    </div>
  );

  return (
    <section className="stack" aria-label="Emails">
      <ErrorNote error={suggested.error} /><ErrorNote error={act.error} />
      {suggested.loading && !suggested.data ? <Loading /> : (
        suggested.data && suggested.data.length > 0 ? (
          <ul className="mb-emails">
            {suggested.data.map((m) => <Mail key={m.id} m={m}>{actions(m)}</Mail>)}
          </ul>
        ) : <Empty>No email is suggested for this deal. Connect a mailbox in Settings and sync, or find one by hand.</Empty>
      )}
      <div>
        <button onClick={() => setFinding((f) => !f)} aria-expanded={finding}>{finding ? "Close search" : "Find an email"}</button>
      </div>
      {finding && (
        <div className="stack">
          <div className="mb-find">
            <label>Search the subject
              <input value={term} maxLength={100} onChange={(ev) => setTerm(ev.target.value)} placeholder="e.g. pricing" />
            </label>
          </div>
          <ErrorNote error={found.error} />
          {found.data && found.data.length === 0 && <Empty>No stored email matches. Only emails from known contacts or account domains are kept.</Empty>}
          <ul className="mb-emails">
            {(found.data ?? []).map((m) => <Mail key={m.id} m={m}>{actions(m)}</Mail>)}
          </ul>
        </div>
      )}
    </section>
  );
}
