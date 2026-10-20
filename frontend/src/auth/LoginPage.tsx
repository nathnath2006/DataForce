import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { useAuth } from "./context";
import "./auth.css";

/** /login: email and password. */
export function LoginPage() {
  const { user, setupNeeded, loading, setMe } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const a = useAction();
  if (!loading && setupNeeded) return <Navigate to="/setup" replace />;
  if (user) return <Navigate to="/" replace />;
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={(ev) => {
        ev.preventDefault();
        void a.run(async () => { setMe(await authApi.login(email, password)); nav("/", { replace: true }); });
      }}>
        <h1>Sign in to DataForce</h1>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        <ErrorNote error={a.error} />
        <button className="primary" disabled={a.busy || email.trim() === ""}>Sign in</button>
      </form>
    </main>
  );
}
