import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { refreshWorkspacesUntil } from "../data/refresh";
import { ErrorNote, toApiError } from "../ui";
import type { ApiError } from "../lib";
import { NameCanvas, type NameMode } from "./NameCanvas";
import { progressOf, STEPS, stepStates } from "./logic";
import type { SetupStatus, WorkspaceKind } from "./types";
import "./onboarding.css";

const POLL_MS = 700;
const REAL_MS = 1200;
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type Phase = "working" | "ready" | "failed" | "interrupted" | "error";

/**
 * Full-screen creation: posts the workspace, follows the server's setup steps (test workspaces), waits
 * until the workspace list holds the new slug, then calls `onReady`. Progress comes only from the server.
 */
export function CreatingScreen(props: {
  kind: WorkspaceKind; name: string; slug: string;
  onReady: (slug: string) => void; onTryAgain: () => void; onChooseAgain: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("working");
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [removing, setRemoving] = useState(false);
  const alive = useRef(false);
  const started = useRef(false);
  const still = reducedMotion();
  const { kind, name, slug, onReady } = props;

  useEffect(() => {
    alive.current = true;
    if (!started.current) {
      started.current = true;
      void (async () => {
        try {
          const w = await api.createWorkspace({ slug, name, kind });
          if (kind === "test" && w.setup_state === "preparing") {
            let misses = 0;
            for (;;) {
              await sleep(POLL_MS);
              if (!alive.current) return;
              let s: SetupStatus;
              try { s = await api.getWorkspaceSetup(slug); misses = 0; } catch (e) { if (++misses >= 5) throw e; continue; }
              if (!alive.current) return;
              setStatus(s);
              setProgress(progressOf(s));
              if (s.state === "failed" || s.state === "interrupted") { setPhase(s.state); return; }
              if (s.state === "ready") break;
            }
          } else {
            setProgress(1);
            await sleep(still ? 300 : REAL_MS);
          }
          await refreshWorkspacesUntil(slug);
          if (!alive.current) return;
          setProgress(1);
          setPhase("ready");
          await sleep(still ? 700 : 1500); // let the name settle and glint
          if (alive.current) onReady(slug);
        } catch (e) {
          if (!alive.current) return;
          setError(toApiError(e));
          setPhase("error");
        }
      })();
    }
    return () => { alive.current = false; };
  }, [kind, name, slug, still, onReady]);

  const removeAndRestart = async () => {
    setRemoving(true);
    try { await api.deleteWorkspace(slug); props.onTryAgain(); } catch (e) { setError(toApiError(e)); setRemoving(false); }
  };

  const mode: NameMode = phase === "ready" ? "ready" : phase === "failed" || phase === "interrupted" || phase === "error" ? "failed" : "working";
  const states = kind === "test" ? stepStates(phase === "ready" ? { state: "ready", step: null, done: 8, total: 8, error: null } : status) : null;
  return (
    <div className="ob-overlay" role="status" aria-live="polite">
      <div className="ob-stage">
        {still ? <h2 className={`ob-name ${phase === "ready" || progress > 0 ? "shown" : ""}`}>{name}</h2> : <NameCanvas text={name} progress={progress} mode={mode} />}
        {states ? (
          <ol className="ob-steps">
            {STEPS.map((s, i) => (
              <li key={s.id} className={states[i]}>
                <span className="ob-mark" aria-hidden="true">{states[i] === "done" ? "✓" : states[i] === "failed" ? "!" : ""}</span>{s.label}
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">{phase === "ready" ? "Your workspace is ready." : "Creating your workspace…"}</p>
        )}
        {phase === "failed" && (
          <div className="ob-note">
            <p>{status?.error ?? "Preparing the test workspace failed; nothing was kept."}</p>
            <div className="row"><button className="primary" onClick={props.onTryAgain}>Try again</button><button className="quiet" onClick={props.onChooseAgain}>Choose again</button></div>
          </div>
        )}
        {phase === "interrupted" && (
          <div className="ob-note">
            <p>The server restarted while preparing. The half-filled workspace can be removed so you can start again.</p>
            <ErrorNote error={error} />
            <div className="row"><button className="primary" disabled={removing} onClick={() => void removeAndRestart()}>Remove and start again</button><button className="quiet" onClick={props.onChooseAgain}>Choose again</button></div>
          </div>
        )}
        {phase === "error" && (
          <div className="ob-note">
            <ErrorNote error={error} />
            <div className="row"><button className="primary" onClick={props.onTryAgain}>Back</button><button className="quiet" onClick={props.onChooseAgain}>Choose again</button></div>
          </div>
        )}
      </div>
    </div>
  );
}
