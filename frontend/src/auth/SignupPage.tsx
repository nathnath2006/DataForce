import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { AuthShell, PasswordField } from "./AuthShell";
import { useAuth } from "./context";

/** /signup: create a workspace with a creation code, or join one with `?token=`. */
export function SignupPage() {
  const [params, setParams] = useSearchParams();
  const token = params.get("token") ?? "";
  const { setMe } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState<"create" | "join">(token ? "join" : "create");
  const [code, setCode] = useState(token);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [closed, setClosed] = useState(false);
  const a = useAction();
  // The join token stays in the form, not in the address bar (browser history, referrers).
  useEffect(() => { if (params.has("token")) setParams({}, { replace: true }); }, [params, setParams]);
  useEffect(() => { authApi.status().then((s) => setClosed(s.signup_enabled === false)).catch(() => {}); }, []);
  const submit = () => {
    if (a.busy) return;
    void a.run(async () => {
      setMe(await authApi.signup({ email, display_name: name, password, mode, code: code.trim() }));
      nav(mode === "create" ? "/welcome" : "/", { replace: true });
    });
  };
  return (
    <AuthShell
      title="Create your account" tab="signup"
      onSubmit={submit}
      footer={<>Already have an account? <Link className="auth-link" to="/login">Sign in</Link></>}
    >
      {closed ? (
        <p className="muted">Sign-up is closed for now. Ask your DataForce administrator for an account.</p>
      ) : (<>
      <div className="auth-seg" role="radiogroup" aria-label="Sign-up type">
        {([["create", "Create my workspace"], ["join", "Join with a token"]] as const).map(([k, l]) => (
          <button key={k} type="button" role="radio" aria-checked={mode === k} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>{l}</button>
        ))}
      </div>
      <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} /></label>
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
      <PasswordField label="Password (at least 10 characters)" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={10} required />
      <label>{mode === "create" ? "Creation code" : "Join token"}
        <input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" spellCheck={false} required />
      </label>
      <ErrorNote error={a.error} />
      <button className="primary" disabled={a.busy}>{a.busy ? "Creating…" : "Create account →"}</button>
      </>)}
    </AuthShell>
  );
}
