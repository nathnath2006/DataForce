import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi, type DemoLogin } from "./api";
import { AuthShell, PasswordField } from "./AuthShell";
import { useAuth } from "./context";

/** /login: email and password, plus one-click demo accounts on this computer. */
export function LoginPage() {
  const { user, setupNeeded, loading, setMe } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [demos, setDemos] = useState<DemoLogin[]>([]);
  const [signupEnabled, setSignupEnabled] = useState(true);
  const a = useAction();
  useEffect(() => { authApi.status().then((s) => { setDemos(s.demo_logins ?? []); setSignupEnabled(s.signup_enabled !== false); }).catch(() => {}); }, []);
  if (!loading && setupNeeded) return <Navigate to="/setup" replace />;
  if (user) return <Navigate to="/" replace />;

  const signIn = (em: string, pw: string) =>
    a.run(async () => { setMe(await authApi.login(em, pw)); nav("/", { replace: true }); });
  const isDemo = demos.some((d) => d.email === email.trim().toLowerCase());
  const failed = a.error?.status === 401;

  return (
    <AuthShell
      title="Sign in to DataForce" tab="login" signupEnabled={signupEnabled}
      onSubmit={() => { if (email.trim() && !a.busy) void signIn(email, password); }}
    >
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" placeholder="you@company.com" autoFocus /></label>
      <PasswordField label="Password" aside={<Link className="auth-link" to="/forgot">Forgot password?</Link>} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      {failed ? (
        <div className="note err" role="alert">
          Wrong email or password.
          {isDemo && password !== "" && <> Demo accounts have no password: leave it empty.</>}
        </div>
      ) : <ErrorNote error={a.error} />}
      <button className="primary" disabled={a.busy || email.trim() === ""}>{a.busy ? "Signing in…" : "Sign in →"}</button>
      {demos.length > 0 && (
        <section className="demo-box" aria-label="Demo accounts">
          <h2>Try a demo account</h2>
          <div className="demo-chips">
            {demos.map((d) => (
              <button type="button" key={d.email} className="demo-chip" disabled={a.busy}
                onClick={() => { setEmail(d.email); setPassword(""); void signIn(d.email, ""); }}>
                <strong>{d.display_name}</strong><span>{d.email}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </AuthShell>
  );
}
