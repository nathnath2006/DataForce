import { useState, type ReactNode } from "react";
import { DEMO_BLOCKED_REASON } from "./demoLogic";
import { DemoAiKeyDialog } from "./DemoAiKeyDialog";

/** One-line note replacing a feature the demo does not offer. */
export function DemoBlockedNote({ title }: { title?: string }) {
  return (
    <div className="card stack" role="note">
      {title && <h2>{title}</h2>}
      <p className="muted">{DEMO_BLOCKED_REASON}.</p>
    </div>
  );
}

/** Settings replacement for the AI key fields in a demo session. */
export function DemoAiKeyCard({ children }: { children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="tile">
      <h2 className="tile-title">Demo AI key</h2>
      <p className="muted small">The workspace AI settings are not available in the demo. Use your own key: it stays in this demo session only and is deleted when you leave.</p>
      <div className="row"><button type="button" className="primary" onClick={() => setOpen(true)}>Use your own key</button></div>
      {children}
      {open && <DemoAiKeyDialog onClose={() => setOpen(false)} />}
    </section>
  );
}
