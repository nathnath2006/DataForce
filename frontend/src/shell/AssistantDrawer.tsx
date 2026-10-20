import { useEffect, useRef, useState } from "react";
import { AskPanel } from "../assistant/AskPanel";
import { loadDrawerOpen, saveDrawerOpen } from "./logic";
import { useDrawerScope } from "./scope";
import "./shell.css";

/** 1.5px outline speech-bubble icon. */
function AssistantIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 5h16v11H9l-5 4z" /><path d="M8 9.5h8M8 12.5h5" />
    </svg>
  );
}

/** Returns the open state and its setter, remembered in safeStorage (key df.drawer). */
export function useDrawerOpen(): [boolean, (o: boolean) => void] {
  const [open, setOpen] = useState(loadDrawerOpen);
  return [open, (o) => { setOpen(o); saveDrawerOpen(o); }];
}

export function AssistantDrawer({ open, setOpen }: { open: boolean; setOpen: (o: boolean) => void }) {
  const scope = useDrawerScope();
  const rail = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const skipFocus = useRef(true);

  useEffect(() => {
    if (skipFocus.current) { skipFocus.current = false; return; }
    if (open) panel.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector("dialog[open]")) return; // let a modal handle its own Escape
      setOpen(false);
      rail.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  return (
    <>
      <aside
        ref={panel} id="df-drawer" tabIndex={-1} className={`drawer ${open ? "open" : ""}`}
        aria-label="Assistant" inert={!open}
      >
        <div className="drawer-head">
          <div>
            <h2>Assistant</h2>
            <p className="drawer-sub">{scope ? `About ${scope.name || `this ${scope.kind}`}` : "No record open"}</p>
          </div>
          <button type="button" className="ghost" aria-label="Close assistant"
            onClick={() => { setOpen(false); rail.current?.focus(); }}>×</button>
        </div>
        <div className="drawer-body">
          {scope ? (
            <AskPanel key={`${scope.kind}:${scope.id}`} scope={{ kind: scope.kind, id: scope.id }} bare />
          ) : (
            <div className="drawer-empty">
              <span className="icon-badge"><AssistantIcon /></span>
              <p className="muted">Open an account or a company to ask about it.</p>
            </div>
          )}
        </div>
      </aside>
      <div className="rail">
        <button
          ref={rail} type="button" className="rail-btn" aria-label="Assistant" title="Assistant"
          aria-expanded={open} aria-controls="df-drawer" onClick={() => setOpen(!open)}
        >
          <AssistantIcon />
        </button>
      </div>
    </>
  );
}
