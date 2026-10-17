import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { Empty, ErrorNote, Field, Loading, Modal, emptyToNull, useAction, useDebounced, useLoad } from "../ui";
import type { ContactOut } from "../types";

export function ContactsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [accountId, setAccountId] = useState("");
  const dq = useDebounced(q);
  const [creating, setCreating] = useState(false);
  const accounts = useLoad(() => api.listAccounts(ws.slug, { limit: 1000 }), [ws.slug]);
  const { data, error, loading } = useLoad(
    () => api.listContacts(ws.slug, { q: dq, account_id: accountId, limit: 1000 }), [ws.slug, dq, accountId]);
  return (
    <section>
      <div className="row between wrap">
        <h1>Contacts</h1>
        <button className="primary" onClick={() => setCreating(true)}>New contact</button>
      </div>
      <div className="row wrap filters">
        <input type="search" placeholder="Search name or title" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        {data && <span className="muted">{data.items.length} of {data.total}</span>}
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data && data.items.length === 0 ? <Empty>No contacts match.</Empty> : data && (
        <div className="tablewrap"><table>
          <thead><tr><th>Name</th><th>Title</th><th>Account</th><th>Reports to</th><th className="num">Notes</th></tr></thead>
          <tbody>{data.items.map((c) => (
            <tr key={c.id}>
              <td><Link to={c.id}>{c.full_name}</Link></td><td>{c.title ?? "—"}</td>
              <td><Link to={`/w/${ws.slug}/accounts/${c.account_id}`}>{c.account_name}</Link></td>
              <td>{c.reports_to_name ?? "—"}</td><td className="num">{c.n_notes}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
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
