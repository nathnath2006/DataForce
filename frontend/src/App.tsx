import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate, useParams } from "react-router";
import { api } from "./api";
import { WsContext } from "./context";
import { ErrorNote, Field, Loading, Modal, safeStorage, useAction, useLoad } from "./ui";
import { AccountsPage } from "./pages/Accounts";
import { AccountDetailPage } from "./pages/AccountDetail";
import { ContactsPage } from "./pages/Contacts";
import { ContactDetailPage } from "./pages/ContactDetail";
import { DealsPage } from "./pages/Deals";
import { AnalysisPage } from "./pages/Analysis";
import { SettingsPage } from "./pages/Settings";
import { CompaniesPage } from "./companies/CompaniesPage";
import { CompanyDetailPage } from "./companies/CompanyDetail";
import { FlowsPage } from "./flows/FlowsPage";
import { ThemeToggle } from "./theme";

// The flow editor (and its canvas library) is the largest part of the bundle: load it on demand.
const FlowEditorPage = lazy(() =>
  import("./flows/FlowEditor").then((m) => ({ default: m.FlowEditorPage })),
);

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/w/:ws" element={<Shell />}>
        <Route index element={<Navigate to="companies" replace />} />
        <Route path="companies" element={<CompaniesPage />} />
        <Route path="companies/:id" element={<CompanyDetailPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="accounts/:id" element={<AccountDetailPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="contacts/:id" element={<ContactDetailPage />} />
        <Route path="deals" element={<DealsPage />} />
        <Route path="analysis" element={<FlowsPage />} />
        <Route path="analysis/scan" element={<AnalysisPage />} />
        <Route path="analysis/:flowId" element={<Suspense fallback={<Loading />}><FlowEditorPage /></Suspense>} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<p className="muted">Page not found.</p>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function Home() {
  const nav = useNavigate();
  const { data, error, reload } = useLoad(() => api.listWorkspaces(), []);
  const [creating, setCreating] = useState(false);
  const first = data?.[0];
  if (first) return <Navigate to={`/w/${first.slug}/accounts`} replace />;
  return (
    <main className="center">
      <h1>DataForce</h1>
      <ErrorNote error={error} />
      {data && data.length === 0 && (
        <>
          <p>No workspace yet.</p>
          <button className="primary" onClick={() => setCreating(true)}>New workspace</button>
        </>
      )}
      {!data && !error && <Loading />}
      {creating && (
        <NewWorkspace onClose={() => setCreating(false)} onCreated={(slug) => { reload(); nav(`/w/${slug}/accounts`); }} />
      )}
    </main>
  );
}

const actingKey = (ws: string) => `dataforce.actingAs.${ws}`;

function Shell() {
  const { ws: slug = "" } = useParams();
  const nav = useNavigate();
  const wss = useLoad(() => api.listWorkspaces(), [slug]);
  const users = useLoad(() => api.listUsers(slug), [slug]);
  const [acting, setActing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [addUser, setAddUser] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => { setActing(safeStorage("get", actingKey(slug))); }, [slug]);

  const ws = wss.data?.find((w) => w.slug === slug);
  const userList = users.data ?? [];
  const actingValid = acting && userList.some((u) => u.id === acting) ? acting : null;

  const pick = (id: string) => {
    if (id === "__new") { setAddUser(true); return; }
    const v = id === "" ? null : id;
    setActing(v);
    safeStorage(v ? "set" : "remove", actingKey(slug), v ?? undefined);
  };

  if (wss.loading && !wss.data) return <main className="center"><Loading /></main>;
  if (wss.error) return <main className="center"><ErrorNote error={wss.error} /></main>;
  if (!ws) return <main className="center"><p>Workspace “{slug}” not found.</p><NavLink to="/">Back</NavLink></main>;

  return (
    <WsContext.Provider
      value={{ ws, users: userList, actingAs: actingValid, refreshUsers: users.reload, refreshWorkspaces: wss.reload }}
    >
      <div className="shell">
        <header className="top">
          <button className="ghost menu" aria-label="Menu" onClick={() => setNavOpen((o) => !o)}>☰</button>
          <strong className="brand">DataForce</strong>
          <select
            aria-label="Workspace" value={slug}
            onChange={(e) => (e.target.value === "__new" ? setCreating(true) : nav(`/w/${e.target.value}/accounts`))}
          >
            {(wss.data ?? []).map((w) => (
              <option key={w.slug} value={w.slug}>
                {w.name}{w.is_demo && !/synthetic/i.test(w.name) ? " (synthetic)" : ""}
              </option>
            ))}
            <option value="__new">+ New workspace…</option>
          </select>
          <span className="spacer" />
          <ThemeToggle />
          <label className="acting">
            <span>Acting as</span>
            <select aria-label="Acting as" value={actingValid ?? ""} onChange={(e) => pick(e.target.value)}>
              <option value="">(nobody)</option>
              {userList.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
              <option value="__new">+ Add user…</option>
            </select>
          </label>
        </header>
        {ws.is_demo && (
          <div className="banner" role="note">Synthetic demo data — generated, no real company or person.</div>
        )}
        <div className="body">
          <nav className={`side ${navOpen ? "open" : ""}`} onClick={() => setNavOpen(false)}>
            {["companies", "accounts", "contacts", "deals", "analysis", "settings"].map((p) => (
              <NavLink key={p} to={`/w/${slug}/${p}`}>{p.charAt(0).toUpperCase() + p.slice(1)}</NavLink>
            ))}
            <p className="muted small">Acting as is a label only: there is no login before M3.</p>
          </nav>
          <main className="content"><Outlet /></main>
        </div>
      </div>
      {creating && (
        <NewWorkspace
          onClose={() => setCreating(false)}
          onCreated={(s) => { wss.reload(); nav(`/w/${s}/accounts`); }}
        />
      )}
      {addUser && (
        <NewUser
          slug={slug} onClose={() => setAddUser(false)}
          onCreated={(id) => { users.reload(); setActing(id); safeStorage("set", actingKey(slug), id); }}
        />
      )}
    </WsContext.Provider>
  );
}

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

function NewWorkspace(props: { onClose: () => void; onCreated: (slug: string) => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [touched, setTouched] = useState(false);
  const a = useAction();
  const effective = touched ? slug : slugify(name);
  const valid = name.trim() !== "" && /^[a-z0-9][a-z0-9-]{0,63}$/.test(effective);
  return (
    <Modal title="New workspace" onClose={props.onClose}>
      <form className="stack" onSubmit={(ev) => {
        ev.preventDefault();
        void a.run(async () => {
          const w = await api.createWorkspace({ slug: effective, name: name.trim() });
          props.onClose();
          props.onCreated(w.slug);
        });
      }}>
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus /></Field>
        <Field label="Slug (lowercase letters, digits, dashes)">
          <input value={effective} onChange={(e) => { setTouched(true); setSlug(e.target.value); }} />
        </Field>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={!valid || a.busy}>Create</button>
        </div>
      </form>
    </Modal>
  );
}

function NewUser(props: { slug: string; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const a = useAction();
  return (
    <Modal title="Add a user" onClose={props.onClose}>
      <form className="stack" onSubmit={(ev) => {
        ev.preventDefault();
        void a.run(async () => {
          const u = await api.createUser(props.slug, { display_name: name.trim() });
          props.onCreated(u.id);
          props.onClose();
        });
      }}>
        <Field label="Display name"><input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus /></Field>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={name.trim() === "" || a.busy}>Add</button>
        </div>
      </form>
    </Modal>
  );
}
