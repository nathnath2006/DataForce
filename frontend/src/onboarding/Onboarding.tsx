import { useCallback, useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { LavaBackground } from "../auth/LavaBackground";
import { Wordmark } from "../auth/Wordmark";
import { useAuth } from "../auth";
import { Field, Modal } from "../ui";
import { CreatingScreen } from "./CreatingScreen";
import { slugify, SLUG_RE } from "./logic";
import type { WorkspaceKind } from "./types";
import "../auth/auth.css";
import "./onboarding.css";

function Chooser(props: { onPick: (k: WorkspaceKind) => void; showTest: boolean }) {
  return (
    <div className="ob-choices">
      {props.showTest && <button type="button" className="ob-choice" onClick={() => props.onPick("test")}>
        <span className="ob-badge">Synthetic</span>
        <strong>Test workspace</strong>
        <span>Synthetic companies, deals, meetings and six demo reps, to try every feature. Always marked as synthetic.</span>
      </button>}
      <button type="button" className="ob-choice" onClick={() => props.onPick("real")}>
        <strong>Real workspace</strong>
        <span>Empty, for your own data: import CSV or Excel, connect TamTam, add records.</span>
      </button>
    </div>
  );
}

function NameForm(props: { kind: WorkspaceKind; name: string; setName: (n: string) => void; slug: string; setSlug: (s: string | null) => void; touched: boolean; onBack: () => void; onCreate: () => void }) {
  const effective = props.touched ? props.slug : slugify(props.name);
  const valid = props.name.trim() !== "" && SLUG_RE.test(effective);
  return (
    <form className="stack" onSubmit={(ev) => { ev.preventDefault(); if (valid) props.onCreate(); }}>
      <Field label={props.kind === "test" ? "Name of the test workspace" : "Name of the workspace"}>
        <input value={props.name} onChange={(e) => props.setName(e.target.value)} required maxLength={200} autoFocus />
      </Field>
      <details className="ob-adv">
        <summary>Advanced</summary>
        <Field label="Slug (lowercase letters, digits, dashes)">
          <input value={effective} onChange={(e) => props.setSlug(e.target.value)} />
        </Field>
      </details>
      <div className="row end">
        <button type="button" className="quiet" onClick={props.onBack}>Back</button>
        <button className="primary" disabled={!valid}>Create</button>
      </div>
    </form>
  );
}

/** Chooser, name form and creation screen. `page` is the /welcome layout, `modal` the top-bar dialog. */
function Flow(props: { variant: "page" | "modal"; onClose?: () => void; onDone: (slug: string) => void }) {
  const { user } = useAuth();
  const showTest = !!user?.is_admin;
  const [step, setStep] = useState<"choose" | "name" | "creating">(showTest ? "choose" : "name");
  const [kind, setKind] = useState<WorkspaceKind>(showTest ? "test" : "real");
  const [name, setName] = useState("");
  const [custom, setCustom] = useState<string | null>(null);
  const slug = custom ?? slugify(name);
  const { onDone } = props;
  const done = useCallback((s: string) => onDone(s), [onDone]);

  if (step === "creating") {
    return (
      <CreatingScreen
        kind={kind} name={name.trim()} slug={slug} onReady={done}
        onTryAgain={() => setStep("name")} onChooseAgain={() => setStep(showTest ? "choose" : "name")}
      />
    );
  }
  const body = step === "choose" ? (
    <Chooser showTest={showTest} onPick={(k) => { setKind(k); setStep("name"); if (!name) setName(k === "test" ? "Test data" : ""); }} />
  ) : (
    <NameForm
      kind={kind} name={name} setName={setName} slug={slug} touched={custom !== null} setSlug={setCustom}
      onBack={() => (showTest ? setStep("choose") : props.onClose?.())} onCreate={() => setStep("creating")}
    />
  );
  if (props.variant === "modal") {
    return <Modal title="New workspace" onClose={props.onClose ?? (() => {})}>{body}</Modal>;
  }
  return (
    <main className="auth-page">
      <LavaBackground />
      <div className="auth-card ob-wide">
        <Wordmark />
        <div className="auth-head">
          <h1>{step === "choose" ? "Set up your first workspace" : kind === "test" ? "Name your test workspace" : "Name your workspace"}</h1>
          <p className="muted">{step === "choose" ? "Start with demo data to look around, or with an empty workspace for your own data." : "You can add more workspaces later."}</p>
        </div>
        {body}
      </div>
    </main>
  );
}

/** /welcome: the superadmin, or an account with workspace credits. */
export function WelcomePage() {
  const { isAdmin, user, loading, refresh } = useAuth();
  const canCreate = isAdmin || (user?.workspace_credits ?? 0) > 0;
  const nav = useNavigate();
  const done = useCallback((s: string) => { void refresh(); nav(`/w/${s}/home`, { replace: true }); }, [nav, refresh]);
  if (loading) return null;
  if (!canCreate) return <Navigate to="/" replace />;
  return <Flow variant="page" onDone={done} />;
}

/** Top-bar "New workspace": same chooser and name form in a dialog, then the full-screen creation. */
export function NewWorkspaceDialog(props: { onClose: () => void; onCreated: (slug: string) => void }) {
  return <Flow variant="modal" onClose={props.onClose} onDone={props.onCreated} />;
}

/** Shown when a workspace is missing after a fresh answer, and to people who are in no workspace. */
export function CalmCard(props: { title: string; text: string; children?: React.ReactNode }) {
  return (
    <main className="auth-page">
      <div className="auth-card">
        <Wordmark />
        <div className="auth-head"><h1>{props.title}</h1><p className="muted">{props.text}</p></div>
        {props.children}
      </div>
    </main>
  );
}
