import { lazy, Suspense, useMemo, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate, useParams } from "react-router";
import { api } from "./api";
import { WsContext } from "./context";
import { LoginPage, RequireAuth, SetupPage, AdminOnly } from "./auth";
import { ErrorNote, Field, Loading, Modal, useAction, useLoad } from "./ui";
import { AccountsPage } from "./pages/Accounts";
import { AccountDetailPage } from "./pages/AccountDetail";
import { ContactsPage } from "./pages/Contacts";
import { ContactDetailPage } from "./pages/ContactDetail";
import { DealsPage } from "./pages/Deals";
import { DealDetailPage } from "./pages/DealDetail";
import { AnalysisPage } from "./pages/Analysis";
import { SettingsPage } from "./pages/Settings";
import { AdminPage } from "./pages/Admin";
import { CompaniesPage } from "./companies/CompaniesPage";
import { CompanyDetailPage } from "./companies/CompanyDetail";
import { MeetingsPage } from "./meetings/MeetingsPage";
import { FlowsPage } from "./flows/FlowsPage";
import { ModelsPage } from "./analysis/ModelsPage";
import { WorkbooksPage } from "./workbooks/WorkbooksPage";
import { SideNav, loadNavCollapsed, saveNavCollapsed } from "./shell/Nav";
import { TopBar } from "./shell/TopBar";
import { AssistantDrawer, useDrawerOpen } from "./shell/AssistantDrawer";
import { ScopeProvider } from "./shell/scope";

// The flow editor (and its canvas library) is the largest part of the bundle: load it on demand.
const FlowEditorPage = lazy(() =>
  import("./flows/FlowEditor").then((m) => ({ default: m.FlowEditorPage })),
);

// Workbooks pull in ECharts: the editor is its own chunk.
const WorkbookEditorPage = lazy(() =>
  import("./workbooks/WorkbookEditor").then((m) => ({ default: m.WorkbookEditorPage })),
);

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/" element={<RequireAuth><Home /></RequireAuth>} />
      <Route path="/w/:ws" element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<Navigate to="companies" replace />} />
        <Route path="companies" element={<CompaniesPage />} />
        <Route path="companies/:id" element={<CompanyDetailPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="accounts/:id" element={<AccountDetailPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="contacts/:id" element={<ContactDetailPage />} />
        <Route path="deals" element={<DealsPage />} />
        <Route path="deals/:id" element={<DealDetailPage />} />
        <Route path="meetings" element={<MeetingsPage />} />
        <Route path="analysis" element={<FlowsPage />} />
        <Route path="analysis/scan" element={<AnalysisPage />} />
        <Route path="analysis/models" element={<ModelsPage />} />
        <Route path="analysis/workbooks" element={<WorkbooksPage />} />
        <Route path="analysis/workbooks/:id" element={<Suspense fallback={<Loading />}><WorkbookEditorPage /></Suspense>} />
        <Route path="analysis/:flowId" element={<Suspense fallback={<Loading />}><FlowEditorPage /></Suspense>} />
        <Route path="settings" element={<AdminOnly><SettingsPage /></AdminOnly>} />
        <Route path="admin" element={<AdminOnly><AdminPage /></AdminOnly>} />
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

function Shell() {
  const { ws: slug = "" } = useParams();
  const nav = useNavigate();
  const wss = useLoad(() => api.listWorkspaces(), [slug]);
  const users = useLoad(() => api.listUsers(slug), [slug]);
  const [creating, setCreating] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(loadNavCollapsed);
  const [drawerOpen, setDrawerOpen] = useDrawerOpen();

  const ws = wss.data?.find((w) => w.slug === slug);
  const userList = users.data ?? [];

  const { reload: reloadUsers } = users;
  const { reload: reloadWorkspaces } = wss;
  const wsValue = useMemo(
    () => (ws ? { ws, users: userList, refreshUsers: reloadUsers, refreshWorkspaces: reloadWorkspaces } : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ws, users.data, reloadUsers, reloadWorkspaces],
  );

  if (wss.loading && !wss.data) return <main className="center"><Loading /></main>;
  if (wss.error) return <main className="center"><ErrorNote error={wss.error} /></main>;
  if (!ws) return <main className="center"><p>Workspace “{slug}” not found.</p><NavLink to="/">Back</NavLink></main>;

  return (
    <WsContext.Provider value={wsValue!}>
      <ScopeProvider>
      <div className="shell">
        <TopBar
          slug={slug} workspaces={wss.data ?? []} onNewWorkspace={() => setCreating(true)}
          onMenu={() => setNavOpen((o) => !o)}
          onToggleNav={() => { setNavCollapsed((c) => { saveNavCollapsed(!c); return !c; }); }}
        />
        {ws.is_demo && (
          <div className="banner" role="note">Synthetic demo data — generated, no real company or person.</div>
        )}
        <div className={`body has-rail ${drawerOpen ? "drawer-open" : ""}`}>
          <SideNav slug={slug} collapsed={navCollapsed} open={navOpen} onNavigate={() => setNavOpen(false)} />
          {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} />}
          <main className="content"><Outlet /></main>
        </div>
        <AssistantDrawer open={drawerOpen} setOpen={setDrawerOpen} />
      </div>
      </ScopeProvider>
      {creating && (
        <NewWorkspace
          onClose={() => setCreating(false)}
          onCreated={(s) => { wss.reload(); nav(`/w/${s}/accounts`); }}
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
