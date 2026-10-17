import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { Empty, ErrorNote, Field, Loading, Modal, emptyToNull, useAction, useDebounced, useLoad } from "../ui";
import type { ContactOut } from "../types";
import { NormalizeButton, ReviewTitles } from "../titles/TitlesToolbar";
import { classLabel } from "../orgchart/model";

export function ContactsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [accountId, setAccountId] = useState("");
  const dq = useDebounced(q);
  const [creating, setCreating] = useState(false);
  const [flagged, setFlagged] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const accounts = useLoad(() => api.listAccounts(ws.slug, { limit: 1000 }), [ws.slug]);
  const { data, error, loading, reload } = useLoad(
    () => api.listContacts(ws.slug, { q: dq, account_id: accountId, limit: 1000 }), [ws.slug, dq, accountId]);
  const shown = (data?.items ?? []).filter((c) => !flagged || !!c.title_flag);
  return (
    <section>
      <div className="row between wrap">
        <h1>Contacts</h1>
        <div className="row wrap">
          <NormalizeButton onDone={reload} />
          <button aria-pressed={reviewing} onClick={() => setReviewing(!reviewing)}>{reviewing ? "Back to list" : "Review titles"}</button>
          <button className="primary" onClick={() => setCreating(true)}>New contact</button>
        </div>
      </div>
      {reviewing ? <ReviewTitles onChanged={reload} /> : <>
      <div className="row wrap filters">
        <input type="search" placeholder="Search name or title" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} />Flagged only</label>
        {data && <span className="muted">{shown.length} of {data.total}</span>}
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data && shown.length === 0 ? <Empty>No contacts match.</Empty> : data && (
        <div className="tablewrap"><table>
          <thead><tr><th>Name</th><th>Title</th><th>Function</th><th>Seniority</th><th>Account</th><th>Reports to</th><th className="num">Notes</th></tr></thead>
          <tbody>{shown.map((c) => (
            <tr key={c.id}>
              <td><Link to={c.id}>{c.full_name}</Link></td><td>{c.title ?? "—"}{c.title_flag && <> <span className="tag warn" title={c.title_flag}>check</span></>}</td>
              <td>{classLabel(c.title_function, "x").split(" · ")[0]}</td><td>{classLabel("x", c.title_seniority).split(" · ")[1]}</td>
              <td><Link to={`/w/${ws.slug}/accounts/${c.account_id}`}>{c.account_name}</Link></td>
              <td>{c.reports_to_name ?? "—"}</td><td className="num">{c.n_notes}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      </>}
      {creating && <ContactForm onClose={() => setCreating(false)} onSaved={(c) => nav(c.id)} />}
    </section>
  );
}

export function ContactForm(props: {
  accountId?: string; contact?: ContactOut; onClose: () => void; onSaved: (c: ContactOut) => void;
}) {
  const { ws } = useWs();
  const c0 = props.contact;
  const [name, setName] = useState(c0?.full_name ?? "");
  const [title, setTitle] = useState(c0?.title ?? "");
  const [accountId, setAccountId] = useState(props.accountId ?? "");
  const accounts = useLoad(() => api.listAccounts(ws.slug, { limit: 1000 }), [ws.slug]);
  const act = useAction();
  return (
    <Modal title={c0 ? "Edit contact" : "New contact"} onClose={props.onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void act.run(async () => {
          const saved = c0
            ? await api.updateContact(ws.slug, c0.id, { full_name: name.trim(), title: emptyToNull(title) })
            : await api.createContact(ws.slug, { account_id: accountId, full_name: name.trim(), title: emptyToNull(title) });
          props.onSaved(saved);
          props.onClose();
        });
      }}>
        <p className="muted small">Only name and title are kept: a strict minimum of personal data.</p>
        <Field label="Full name"><input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus /></Field>
        <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></Field>
        {!c0 && !props.accountId && (
          <Field label="Account">
            <select value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
              <option value="">Choose…</option>
              {accounts.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
        )}
        <ErrorNote error={act.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={act.busy || name.trim() === "" || (!c0 && accountId === "")}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
