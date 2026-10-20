import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useWs } from "../context";
import type { CompanyOut, RegistryCompanyOut } from "../types";
import { Empty, ErrorNote, Field, Loading, Modal, Tag, emptyToNull, useAction, useDebounced, useLoad } from "../ui";
import { companiesApi } from "./api";
import { registrySummary } from "./format";

const PAGE = 25;

export function InteractedBadge({ c }: { c: Pick<CompanyOut, "interacted" | "last_interaction"> }) {
  return c.interacted
    ? <Tag kind="ok">interacted{c.last_interaction ? ` · ${c.last_interaction.slice(0, 10)}` : ""}</Tag>
    : <Tag kind="mute">no interaction</Tag>;
}

export function CompaniesPage() {
  const { ws } = useWs();
  const nav = useNavigate();
  const base = `/w/${ws.slug}`;
  const [params] = useSearchParams();
  const [text, setText] = useState(params.get("q") ?? "");
  const dq = useDebounced(text.trim(), 250);
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [hits, setHits] = useState<RegistryCompanyOut[] | null>(null);
  const [addFor, setAddFor] = useState<RegistryCompanyOut | null>(null);
  const reg = useAction();

  const lookup = useLoad(() => (dq ? companiesApi.lookup(ws.slug, dq) : Promise.resolve(null)), [ws.slug, dq]);
  const list = useLoad(() => (dq ? Promise.resolve(null) : companiesApi.list(ws.slug, { limit: PAGE, offset })), [ws.slug, dq, offset]);

  const searchRegistry = () => {
    if (text.trim().length < 2) return;
    void reg.run(async () => { setHits(await companiesApi.registrySearch(ws.slug, text.trim())); });
  };

  const row = (c: CompanyOut) => (
    <tr key={c.id}>
      <td><Link to={`${base}/companies/${c.id}`}>{c.name}</Link></td>
      <td>{c.siren ?? "—"}</td><td>{c.city ?? "—"}</td>
      <td className="num">{c.n_accounts}</td><td className="num">{c.n_deals}</td>
      <td><InteractedBadge c={c} /></td>
    </tr>
  );
  const head = <thead><tr><th>Company</th><th>SIREN</th><th>City</th><th className="num">Accounts</th><th className="num">Deals</th><th>Interaction</th></tr></thead>;
  const l = lookup.data;

  return (
    <section className="stack">
      <div className="row between wrap">
        <h1>Companies</h1>
        <button className="primary" onClick={() => setCreating(true)}>New company</button>
      </div>
      <form className="row wrap" onSubmit={(ev) => { ev.preventDefault(); searchRegistry(); }}>
        <input type="search" aria-label="Search companies" placeholder="Name, domain or SIREN" value={text}
          onChange={(ev) => { setText(ev.target.value); setOffset(0); setHits(null); }} style={{ flex: 1, minWidth: 220 }} />
        <button type="submit" disabled={reg.busy || text.trim().length < 2}>Search the public registry</button>
      </form>
      <p className="muted small">
        Typing searches your CRM only. The registry button sends your search text to the public French company
        registry (api.gouv.fr).
      </p>
      <ErrorNote error={lookup.error} /><ErrorNote error={list.error} /><ErrorNote error={reg.error} />

      {hits && (
        <div className="card">
          <h2>Public registry results ({hits.length})</h2>
          {hits.length === 0 && <Empty>No match in the registry.</Empty>}
          {hits.map((r) => (
            <div key={r.siren} className="hit">
              <div>
                <strong>{r.name}</strong> {r.sole_trader && <Tag kind="mute">sole trader</Tag>}{" "}
                {!r.active && <Tag kind="bad">closed</Tag>}{" "}
                {r.protected && <Tag kind="warn">protected record</Tag>}
                <div className="muted small">{registrySummary(r)}</div>
              </div>
              {r.in_crm_company_id
                ? <Link to={`${base}/companies/${r.in_crm_company_id}`}>Already in your CRM</Link>
                : r.protected
                  ? <span className="muted small" title="The company asked the registry not to publish its details">Cannot be added</span>
                  : <button onClick={() => setAddFor(r)}>Add to CRM</button>}
            </div>
          ))}
        </div>
      )}

      {dq ? (
        lookup.loading && !l ? <Loading /> : l && (
          <div className="card stack">
            <h2>In your CRM</h2>
            {l.companies.length === 0 && l.accounts.length === 0 && <Empty>No match in your CRM. Try the public registry.</Empty>}
            {l.companies.length > 0 && <div className="tablewrap"><table>{head}<tbody>{l.companies.map(row)}</tbody></table></div>}
            {l.accounts.length > 0 && (
              <>
                <h3>Accounts without a company</h3>
                <ul className="plain">{l.accounts.map((a) => (
                  <li key={a.id}><Link to={`${base}/accounts/${a.id}`}>{a.name}</Link> {a.domain && <span className="muted small">{a.domain}</span>}</li>
                ))}</ul>
              </>
            )}
          </div>
        )
      ) : list.loading && !list.data ? <Loading /> : list.data && (
        <div className="card stack">
          {list.data.items.length === 0 ? <Empty>No companies yet.</Empty> : (
            <div className="tablewrap"><table>{head}<tbody>{list.data.items.map(row)}</tbody></table></div>
          )}
          <div className="row between">
            <span className="muted small">{list.data.total} companies</span>
            <div className="row">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
              <button disabled={offset + PAGE >= list.data.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
            </div>
          </div>
        </div>
      )}

      {creating && <CompanyForm onClose={() => setCreating(false)} onSaved={(c) => nav(`${base}/companies/${c.id}`)} />}
      {addFor && (
        <AddFromRegistry r={addFor} onClose={() => setAddFor(null)}
          onAdded={(c) => nav(`${base}/companies/${c.id}`)} />
      )}
    </section>
  );
}

function AddFromRegistry(props: { r: RegistryCompanyOut; onClose: () => void; onAdded: (c: CompanyOut) => void }) {
  const { ws } = useWs();
  const [withAccount, setWithAccount] = useState(false);
  const a = useAction();
  return (
    <Modal title="Add to CRM" onClose={props.onClose}>
      <div className="stack">
        <p><strong>{props.r.name}</strong><br /><span className="muted small">{registrySummary(props.r)}</span></p>
        {props.r.sole_trader && (
          <div className="note warn">This is a sole trader: the name is a person&apos;s name. It is stored only because you add it.</div>
        )}
        <label className="check">
          <input type="checkbox" checked={withAccount} onChange={(e) => setWithAccount(e.target.checked)} />
          Create an account too
        </label>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy} onClick={() => void a.run(async () => {
            props.onAdded(await companiesApi.fromRegistry(ws.slug, props.r.siren, withAccount));
          })}>Add</button>
        </div>
      </div>
    </Modal>
  );
}

export function CompanyForm(props: { company?: CompanyOut; onClose: () => void; onSaved: (c: CompanyOut) => void }) {
  const { ws } = useWs();
  const c = props.company;
  const [f, setF] = useState({
    name: c?.name ?? "", siren: c?.siren ?? "", domain: c?.domain ?? "", address_line: c?.address_line ?? "",
    postal_code: c?.postal_code ?? "", city: c?.city ?? "", country: c?.country ?? "",
  });
  const a = useAction();
  const set = (k: keyof typeof f) => (ev: { target: { value: string } }) => setF({ ...f, [k]: ev.target.value });
  const save = () => void a.run(async () => {
    const body = {
      name: f.name.trim(), siren: emptyToNull(f.siren), domain: emptyToNull(f.domain),
      address_line: emptyToNull(f.address_line), postal_code: emptyToNull(f.postal_code),
      city: emptyToNull(f.city), country: emptyToNull(f.country)?.toUpperCase() ?? null,
    };
    const out = c ? await companiesApi.update(ws.slug, c.id, body) : await companiesApi.create(ws.slug, body);
    props.onSaved(out);
    props.onClose();
  });
  return (
    <Modal title={c ? "Edit company" : "New company"} onClose={props.onClose}>
      <form className="stack" onSubmit={(ev) => { ev.preventDefault(); save(); }}>
        <Field label="Name"><input required value={f.name} onChange={set("name")} /></Field>
        <div className="grid2">
          <Field label="SIREN (9 digits)"><input value={f.siren} inputMode="numeric" pattern="\d{9}" onChange={set("siren")} /></Field>
          <Field label="Domain"><input value={f.domain} onChange={set("domain")} /></Field>
        </div>
        <Field label="Address"><input value={f.address_line} onChange={set("address_line")} /></Field>
        <div className="grid2">
          <Field label="Postal code"><input value={f.postal_code} onChange={set("postal_code")} /></Field>
          <Field label="City"><input value={f.city} onChange={set("city")} /></Field>
        </div>
        <Field label="Country (2 letters)"><input value={f.country} maxLength={2} onChange={set("country")} /></Field>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" type="submit" disabled={a.busy || !f.name.trim()}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
