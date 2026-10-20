import { useState, type InputHTMLAttributes, type ReactNode } from "react";
import { LavaBackground } from "./LavaBackground";
import { Wordmark } from "./Wordmark";
import "./auth.css";

/** Page frame shared by sign-in, setup, forgot and reset: lava background plus a card. */
export function AuthShell(props: {
  title: string; subtitle?: ReactNode; children: ReactNode; onSubmit: () => void; footer?: ReactNode;
}) {
  return (
    <main className="auth-page">
      <LavaBackground />
      <form className="auth-card" onSubmit={(ev) => { ev.preventDefault(); props.onSubmit(); }}>
        <Wordmark />
        <div className="auth-head">
          <h1>{props.title}</h1>
          {props.subtitle && <p className="muted">{props.subtitle}</p>}
        </div>
        {props.children}
        {props.footer && <div className="auth-foot">{props.footer}</div>}
      </form>
    </main>
  );
}

/** Password input with a show/hide eye button. */
export function PasswordField({ label, ...rest }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false);
  return (
    <label>{label}
      <span className="pw-wrap">
        <input {...rest} type={show ? "text" : "password"} />
        <button type="button" className="pw-eye" aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} onClick={() => setShow(!show)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />
            {show && <path d="M3 3l18 18" />}
          </svg>
        </button>
      </span>
    </label>
  );
}
