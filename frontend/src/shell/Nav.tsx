import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { useAuth } from "../auth";
import { Icon as SharedIcon, type IconName } from "../icons";
import { safeStorage } from "../ui";
import "./shell.css";

const NAV_KEY = "df.nav";
export const loadNavCollapsed = (): boolean => safeStorage("get", NAV_KEY) === "collapsed";
export const saveNavCollapsed = (c: boolean): void => { safeStorage("set", NAV_KEY, c ? "collapsed" : "open"); };

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
  );
}

/** Nav keys that have a drawn icon in icons.tsx (the PO redesign); the rest keep the small local glyphs below. */
const SHARED: Record<string, IconName> = {
  summary: "summary", companies: "companies", accounts: "accounts", contacts: "contacts", deals: "deals",
  meetings: "meetings", flows: "analysis", workbooks: "chart", models: "model", insights: "sparkle",
  settings: "settings", admin: "admin", me: "user", docs: "docs",
};

const ICONS: Record<string, ReactNode> = {
  home: <><path d="M4 11l8-7 8 7" /><path d="M6 10v10h12V10" /><path d="M10 20v-6h4v6" /></>,
  tasks: <><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8 12l3 3 5-6" /></>,
  companies: <><path d="M4 21V4h10v17" /><path d="M14 9h6v12" /><path d="M8 8h2M8 12h2M8 16h2" /></>,
  accounts: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V4h6v3" /></>,
  contacts: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4 4-6 8-6s7 2 8 6" /></>,
  deals: <><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>,
  meetings: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></>,
  flows: <><circle cx="5" cy="6" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="12" r="2" /><path d="M7 6h4a4 4 0 0 1 4 4v1M7 18h4a4 4 0 0 0 4-4v-1" /></>,
  workbooks: <><path d="M4 20V10M10 20V4M16 20v-8M22 20H2" /></>,
  models: <><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></>,
  insights: <><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></>,
  admin: <><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>,
  me: <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></>,
  docs: <><path d="M6 3h9l3 3v15H6z" /><path d="M9 9h6M9 13h6M9 17h4" /></>,
};

interface Item { key: string; label: string; to: string }
interface Group { title: string; items: Item[]; adminOnly?: boolean }

export const NAV_GROUPS: Group[] = [
  { title: "My work", items: [
    { key: "home", label: "Home", to: "home" },
    { key: "tasks", label: "Tasks", to: "tasks" } ] },
  { title: "Customers", items: [
    { key: "companies", label: "Companies", to: "companies" },
    { key: "accounts", label: "Accounts", to: "accounts" },
    { key: "contacts", label: "Contacts", to: "contacts" } ] },
  { title: "Sales", items: [
    { key: "deals", label: "Deals", to: "deals" },
    { key: "meetings", label: "Meetings", to: "meetings" } ] },
  { title: "Analysis", items: [
    { key: "flows", label: "Flows", to: "analysis" },
    { key: "workbooks", label: "Workbooks", to: "analysis/workbooks" },
    { key: "models", label: "Models", to: "analysis/models" },
    { key: "insights", label: "Pipeline scan", to: "analysis/scan" } ] },
  { title: "You", items: [
    { key: "me", label: "My settings", to: "me" },
    { key: "docs", label: "Documentation", to: "docs" } ] },
  { title: "Admin", adminOnly: true, items: [
    { key: "settings", label: "Settings", to: "settings" },
    { key: "admin", label: "Admin", to: "admin" } ] },
];

/** Flows lives at /analysis and /analysis/:flowId; the other analysis pages have their own entries. */
export function navActive(itemKey: string, rest: string): boolean {
  if (itemKey === "flows") return rest === "analysis" || (rest.startsWith("analysis/") && !/^analysis\/(workbooks|models|scan)(\/|$)/.test(rest));
  const it = NAV_GROUPS.flatMap((g) => g.items).find((i) => i.key === itemKey);
  return !!it && (rest === it.to || rest.startsWith(`${it.to}/`));
}

export function SideNav(props: { slug: string; collapsed: boolean; open: boolean; onNavigate: () => void }) {
  const { isAdmin } = useAuth();
  const loc = useLocation();
  const rest = loc.pathname.replace(`/w/${props.slug}/`, "").replace(/\/$/, "");
  return (
    <nav className={`side ${props.collapsed ? "collapsed" : ""} ${props.open ? "open" : ""}`} aria-label="Main" onClick={props.onNavigate}>
      {NAV_GROUPS.filter((g) => !g.adminOnly || isAdmin).map((g) => (
        <div className="nav-group" key={g.title}>
          <p className="nav-title">{g.title}</p>
          {g.items.map((i) => (
            <NavLink key={i.key} to={`/w/${props.slug}/${i.to}`} title={i.label}
              className={() => (navActive(i.key, rest) ? "active" : "")} aria-current={navActive(i.key, rest) ? "page" : undefined}>
              {SHARED[i.key] ? <SharedIcon name={SHARED[i.key]!} size={16} className="ico" /> : <Icon>{ICONS[i.key]}</Icon>}<span className="nav-label">{i.label}</span>
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}
