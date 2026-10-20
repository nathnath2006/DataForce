import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { demoApi } from "./demoApi";
import { AuthShell, PasswordField } from "./AuthShell";
import { useAuth } from "./context";

/** /login: email and password, plus "Try the demo" when the server offers it. */
export function LoginPage() {
  const { user, setupNeeded, loading, setMe } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [demoAvailable, setDemoAvailable] = useState(false);
  const [signupEnabled, setSignupEnabled] = useState(true);
  const a = useAction();
  useEffect(() => { authApi.status().then((s) => { setDemoAvailable(s.demo_available === true); setSignupEnabled(s.signup_enabled !== false); }).catch(() => {}); }, []);
  if (!loading && setupNeeded) return <Navigate to="/setup" replace />;
  if (user) return <Navigate to="/" replace />;

  const signIn = (em: string, pw: string) =>
    a.run(async () => { setMe(await authApi.login(em, pw)); nav("/", { replace: true }); });
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
        </div>
      ) : <ErrorNote error={a.error} />}
      <button className="primary" disabled={a.busy || email.trim() === ""}>{a.busy ? "Signing in…" : "Sign in →"}</button>
      {demoAvailable && (
        <button type="button" className="demo-try" disabled={a.busy}
          onClick={() => void a.run(async () => {
            const me = await demoApi.start();
            setMe(me);
            const slug = me.memberships[0]?.workspace_slug;
            nav(slug ? `/w/${slug}/home` : "/", { replace: true });
          })}>
          Try the demo — no account needed
        </button>
      )}
    </AuthShell>
  );
}
