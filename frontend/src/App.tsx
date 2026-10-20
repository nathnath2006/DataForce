import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Outlet, Route, Routes, useNavigate, useParams } from "react-router";
import { api } from "./api";
import { WsContext } from "./context";
import { ForgotPage, LoginPage, RequireAuth, ResetPage, SetupPage, AdminOnly, useAuth } from "./auth";
import { ErrorNote, Loading } from "./ui";
import type { WorkspaceOut } from "./types";
import { CalmCard, NewWorkspaceDialog, WelcomePage } from "./onboarding";
import { invalidate, useQuery } from "./data/useQuery";
import { SideNav, loadNavCollapsed, saveNavCollapsed } from "./shell/Nav";
import { TopBar } from "./shell/TopBar";
import { AssistantDrawer, useDrawerOpen } from "./shell/AssistantDrawer";
import { ScopeProvider } from "./shell/scope";

// Every page is its own chunk, loaded on first visit (the shell and login stay in the main chunk).
const HomePage = lazy(() => import("./pages/Home").then((m) => ({ default: m.HomePage })));
const TasksPage = lazy(() => import("./pages/Tasks").then((m) => ({ default: m.TasksPage })));
const ActivitiesPage = lazy(() => import("./pages/Activities").then((m) => ({ default: m.ActivitiesPage })));
const AccountsPage = lazy(() => import("./pages/Accounts").then((m) => ({ default: m.AccountsPage })));
const AccountDetailPage = lazy(() => import("./pages/AccountDetail").then((m) => ({ default: m.AccountDetailPage })));
const ContactsPage = lazy(() => import("./pages/Contacts").then((m) => ({ default: m.ContactsPage })));
const ContactDetailPage = lazy(() => import("./pages/ContactDetail").then((m) => ({ default: m.ContactDetailPage })));
const DealsPage = lazy(() => import("./pages/Deals").then((m) => ({ default: m.DealsPage })));
const DealDetailPage = lazy(() => import("./pages/DealDetail").then((m) => ({ default: m.DealDetailPage })));
const AnalysisPage = lazy(() => import("./pages/Analysis").then((m) => ({ default: m.AnalysisPage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));
const AdminPage = lazy(() => import("./pages/Admin").then((m) => ({ default: m.AdminPage })));
const MySettingsPage = lazy(() => import("./pages/MySettings").then((m) => ({ default: m.MySettingsPage })));
const SummaryPage = lazy(() => import("./pages/Summary").then((m) => ({ default: m.SummaryPage })));
const DocsPage = lazy(() => import("./docs/DocsPage").then((m) => ({ default: m.DocsPage })));
const CompaniesPage = lazy(() => import("./companies/CompaniesPage").then((m) => ({ default: m.CompaniesPage })));
const CompanyDetailPage = lazy(() => import("./companies/CompanyDetail").then((m) => ({ default: m.CompanyDetailPage })));
const MeetingsPage = lazy(() => import("./meetings/MeetingsPage").then((m) => ({ default: m.MeetingsPage })));
const FlowsPage = lazy(() => import("./flows/FlowsPage").then((m) => ({ default: m.FlowsPage })));
const ModelsPage = lazy(() => import("./analysis/ModelsPage").then((m) => ({ default: m.ModelsPage })));
const WorkbooksPage = lazy(() => import("./workbooks/WorkbooksPage").then((m) => ({ default: m.WorkbooksPage })));

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
      <Route path="/forgot" element={<ForgotPage />} />
      <Route path="/reset" element={<ResetPage />} />
      <Route path="/welcome" element={<RequireAuth><WelcomePage /></RequireAuth>} />
      <Route path="/" element={<RequireAuth><Home /></RequireAuth>} />
      <Route path="/w/:ws" element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<HomePage />} />
        <Route path="home" element={<HomePage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="activities" element={<ActivitiesPage />} />
        <Route path="summary" element={<SummaryPage />} />
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
        <Route path="me" element={<MySettingsPage />} />
        <Route path="docs" element={<DocsPage />} />
        <Route path="docs/:topic" element={<DocsPage />} />
        <Route path="*" element={<p className="muted">Page not found.</p>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function Home() {
  const { data, error } = useQuery("/workspaces", () => api.listWorkspaces());
  const { isAdmin } = useAuth();
  const first = data?.[0];
  if (first) return <Navigate to={`/w/${first.slug}/home`} replace />;
  if (data && data.length === 0) {
    if (isAdmin) return <Navigate to="/welcome" replace />;
    return <CalmCard title="You are not in a workspace yet" text="Ask your administrator to add you." />;
  }
  return (
    <main className="center">
      <h1>DataForce</h1>
      <ErrorNote error={error} />
      {!data && !error && <Loading />}
    </main>
  );
}

function Shell() {
  const { ws: slug = "" } = useParams();
  const nav = useNavigate();
  // Both start at once and are cached: switching back to a workspace shows it without a round trip.
  const wss = useQuery("/workspaces", () => api.listWorkspaces());
  const users = useQuery(`/w/${encodeURIComponent(slug)}/users`, () => api.listUsers(slug));
  const [creating, setCreating] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(loadNavCollapsed);
  const [drawerOpen, setDrawerOpen] = useDrawerOpen();

  // A list cached before this workspace existed must not decide "not found": ask the server once.
  const [fresh, setFresh] = useState<{ slug: string; list: WorkspaceOut[] } | null>(null);
  const checking = useRef<string | null>(null);
  const known = wss.data?.some((w) => w.slug === slug) ?? false;
  useEffect(() => {
    if (known || !wss.data || checking.current === slug) return;
    checking.current = slug;
    api.listWorkspaces().then(
      (list) => { setFresh({ slug, list }); if (list.some((w) => w.slug === slug)) invalidate("/workspaces"); },
      () => setFresh({ slug, list: [] }),
    );
  }, [known, wss.data, slug]);
  const confirmed = fresh?.slug === slug;
  const ws = (wss.data ?? []).find((w) => w.slug === slug) ?? (confirmed ? fresh.list.find((w) => w.slug === slug) : undefined);
  const userList = users.data ?? [];

  const { reload: reloadUsers } = users;
  const { reload: reloadWorkspaces } = wss;
  const wsValue = useMemo(
    () => (ws ? { ws, users: userList, refreshUsers: reloadUsers, refreshWorkspaces: reloadWorkspaces } : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ws, users.data, reloadUsers, reloadWorkspaces],
  );

  if (wss.loading) return <main className="center"><Loading /></main>;
  if (wss.error) return <main className="center"><ErrorNote error={wss.error} /></main>;
  if (!ws && !confirmed) return <main className="center"><Loading /></main>;
  if (!ws) {
    return (
      <CalmCard title="Workspace not found" text={`There is no workspace “${slug}” that you can open.`}>
        <button className="primary" onClick={() => nav("/")}>Back to my workspaces</button>
      </CalmCard>
    );
  }

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
          <main className="content"><Suspense fallback={<Loading />}><Outlet /></Suspense></main>
        </div>
        <AssistantDrawer open={drawerOpen} setOpen={setDrawerOpen} />
      </div>
      </ScopeProvider>
      {creating && (
        <NewWorkspaceDialog
          onClose={() => setCreating(false)}
          onCreated={(s) => { setCreating(false); nav(`/w/${s}/home`); }}
        />
      )}
    </WsContext.Provider>
  );
}
