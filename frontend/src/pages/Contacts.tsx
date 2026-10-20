import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../api";
import { useWs } from "../context";
import { ErrorNote, Field, Modal, emptyToNull, useAction } from "../ui";
import { DataTable, type Column } from "../table/DataTable";
import { Pager } from "../table/Pager";
import { useListQuery, useUrlSearch } from "../table/useListQuery";
import { AccountPicker } from "../ui/pickers";
import type { ContactOut } from "../types";
import { NormalizeButton, ReviewTitles } from "../titles/TitlesToolbar";
import { classLabel } from "../orgchart/model";

const CONTACT_COLUMNS = (slug: string): Column<ContactOut>[] => [
  { key: "full_name", header: "Name", sortable: true, cell: (c) => c.full_name },
  { key: "title", header: "Title", sortable: true, cell: (c) => <>{c.title ?? "—"}{c.title_flag && <> <span className="tag warn" title={c.title_flag}>check</span></>}</> },
  { key: "title_function", header: "Function", sortable: true, cell: (c) => classLabel(c.title_function, "x").split(" · ")[0] },
  { key: "title_seniority", header: "Seniority", sortable: true, cell: (c) => classLabel("x", c.title_seniority).split(" · ")[1] },
  { key: "account", header: "Account", cell: (c) => <Link to={`/w/${slug}/accounts/${c.account_id}`}>{c.account_name}</Link> },
  { key: "reports_to", header: "Reports to", cell: (c) => c.reports_to_name ?? "—" },
  { key: "n_notes", header: "Notes", numeric: true, cell: (c) => c.n_notes },
];

export function ContactsPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const [creating, setCreating] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const list = useListQuery<ContactOut>({
    resource: "contacts", filters: ["q", "account_id"], defaultSort: { key: "full_name", dir: "asc" },
    fetch: (p, signal) => api.listContacts(ws.slug, p, signal),
  });
  const [text, setText] = useUrlSearch(list.f("q"), (v) => list.setFilter("q", v, true));
  const { data, reload } = list;
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
        <input type="search" placeholder="Search name or title" aria-label="Search" value={text} onChange={(e) => setText(e.target.value)} />
        <div style={{ minWidth: 240 }}>
          <AccountPicker id={list.f("account_id")} ariaLabel="Filter by account" onChange={(id) => list.setFilter("account_id", id)} />
        </div>
      </div>
      <ErrorNote error={list.error} />
      <DataTable columns={CONTACT_COLUMNS(ws.slug)} rows={data?.items ?? []} rowKey={(c) => c.id} rowHref={(c) => c.id}
        sort={list.sort} onSort={list.setSort} loading={list.loading} caption="Contacts" empty="No contacts match." />
      {data && <Pager offset={data.offset} limit={data.limit} shown={data.items.length} total={data.total} onOffset={list.setOffset} />}
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
            <AccountPicker id={accountId} onChange={setAccountId} required />
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
