import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { Wordmark } from "./Wordmark";
import "./auth.css";

const Shield = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" />
  </svg>
);

/** Right panel: thin rings, one dashed ring turning, the logo mark and three badges orbiting slowly. */
function TrustOrbit() {
  const badges = ["Numbers from SQL, never from a model", "Data hosted in the EU", "API keys sealed"];
  return (
    <aside className="auth-side" aria-label="Why you can trust the numbers">
      <div className="orbit" aria-hidden="false">
        <span className="ring r1" /><span className="ring r2" /><span className="ring r3 dashed" /><span className="ring r4" />
        <span className="orbit-logo" aria-hidden="true">
          <svg width="44" height="44" viewBox="0 0 24 24"><path d="M7 17V7h4.5a5 5 0 0 1 0 10z" fill="none" stroke="var(--primary-ink)" strokeWidth="2.2" strokeLinejoin="round" /></svg>
        </span>
        {badges.map((b, i) => (
          <span key={b} className={`orbit-arm a${i}`}><span className="orbit-badge"><Shield />{b}</span></span>
        ))}
      </div>
      <p className="auth-statement">Every figure is computed by SQL or the statistics engine and marked verified only when a test backs it.</p>
    </aside>
  );
}

/** Split page frame shared by sign-in, sign-up, setup, forgot and reset. */
export function AuthShell(props: {
  title: string; subtitle?: ReactNode; children: ReactNode; onSubmit: () => void; footer?: ReactNode;
  tab?: "login" | "signup";
  /** From /api/auth/status; the Log in / Sign up tabs hide when sign-up is off. */
  signupEnabled?: boolean;
}) {
  const nav = useNavigate();
  const { search } = useLocation();
  return (
    <main className="auth-split">
      <div className="auth-main">
        <header className="auth-top">
          <Wordmark />
          <span className="auth-help muted">Need help? Ask your DataForce admin</span>
        </header>
        <form className="auth-form" onSubmit={(ev) => { ev.preventDefault(); props.onSubmit(); }}>
          <div className="auth-head">
            <h1>{props.title}</h1>
            <p className="muted">{props.subtitle ?? "Your pipeline, analyses and verified numbers in one place."}</p>
          </div>
          {props.tab && props.signupEnabled !== false && (
            <div className="auth-tabs" role="tablist">
              {([["login", "Log in", "/login"], ["signup", "Sign up", "/signup"]] as const).map(([k, l, to]) => (
                <button key={k} type="button" role="tab" aria-selected={props.tab === k} className={props.tab === k ? "on" : ""}
                  onClick={() => { if (props.tab !== k) nav(k === "signup" ? to + search : to); }}>{l}</button>
              ))}
            </div>
          )}
          {props.children}
          {props.footer && <div className="auth-foot">{props.footer}</div>}
        </form>
        <footer className="auth-safe"><Shield />Data stays in the EU · passwords hashed · sessions are secure cookies</footer>
      </div>
      <TrustOrbit />
    </main>
  );
}

/** Password input with a show/hide eye button. */
export function PasswordField({ label, aside, ...rest }: { label: string; aside?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false);
  const id = useId();
  return (
    <div className="pw-field">
      <span className="pw-row"><label htmlFor={id}>{label}</label>{aside}</span>
      <span className="pw-wrap">
        <input id={id} {...rest} type={show ? "text" : "password"} />
        <button type="button" className="pw-eye" aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} onClick={() => setShow(!show)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />
            {show && <path d="M3 3l18 18" />}
          </svg>
        </button>
      </span>
    </div>
  );
}
