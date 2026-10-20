import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { UserMenu } from "../auth";
import { ThemeToggle } from "../theme";
import "./shell.css";

export function TopBar(props: {
  slug: string; workspaces: { slug: string; name: string; is_demo: boolean }[];
  onNewWorkspace: () => void; onMenu: () => void; onToggleNav: () => void; children?: ReactNode;
}) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  return (
    <header className="top">
      <button className="ghost menu" aria-label="Menu" onClick={props.onMenu}>☰</button>
      <button className="ghost collapse-btn" aria-label="Collapse navigation" title="Collapse navigation" onClick={props.onToggleNav}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></svg>
      </button>
      <span className="brand"><span className="logo" aria-hidden="true" /><span className="brand-name">DataForce</span></span>
      <select
        className="ws-switch" aria-label="Workspace" value={props.slug}
        onChange={(e) => (e.target.value === "__new" ? props.onNewWorkspace() : nav(`/w/${e.target.value}/accounts`))}
      >
        {props.workspaces.map((w) => (
          <option key={w.slug} value={w.slug}>
            {w.name}{w.is_demo && !/synthetic/i.test(w.name) ? " (synthetic)" : ""}
          </option>
        ))}
        <option value="__new">+ New workspace…</option>
      </select>
      <form className="gsearch" role="search" onSubmit={(e) => {
        e.preventDefault();
        const t = q.trim();
        nav(`/w/${props.slug}/companies${t ? `?q=${encodeURIComponent(t)}` : ""}`);
      }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        <input type="search" aria-label="Search" placeholder="Search companies" value={q} onChange={(e) => setQ(e.target.value)} />
      </form>
      <span className="spacer" />
      <ThemeToggle />
      {props.children}
      <UserMenu />
    </header>
  );
}
