import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { useAuth } from "./context";
import "./auth.css";

/** /setup: shown once, while no admin exists. */
export function SetupPage() {
  const { setupNeeded, loading, setMe } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const a = useAction();
  if (!loading && !setupNeeded) return <Navigate to="/" replace />;
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={(ev) => {
        ev.preventDefault();
        void a.run(async () => {
          setMe(await authApi.setup({ email, display_name: name, password }));
          nav("/", { replace: true });
        });
      }}>
        <h1>Welcome to DataForce</h1>
        <p className="muted">Create the administrator account.</p>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus /></label>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
        <label>Password (at least 10 characters)<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={10} required /></label>
        <ErrorNote error={a.error} />
        <button className="primary" disabled={a.busy}>Create administrator</button>
      </form>
    </main>
  );
}
