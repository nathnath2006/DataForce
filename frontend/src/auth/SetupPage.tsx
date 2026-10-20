import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { AuthShell, PasswordField } from "./AuthShell";
import { useAuth } from "./context";

/** /setup: shown once, while no admin exists. */
export function SetupPage() {
  const { setupNeeded, loading, setMe } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const a = useAction();
  if (!loading && !setupNeeded) return <Navigate to="/login" replace />;
  return (
    <AuthShell
      title="Set up DataForce" subtitle="This creates the administrator, who manages the workspaces and the other people."
      onSubmit={() => { if (!a.busy) void a.run(async () => { setMe(await authApi.setup({ email, display_name: name, password })); nav("/", { replace: true }); }); }}
      footer={<>Already set up? <Link className="auth-link" to="/login">Sign in</Link></>}
    >
      <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus /></label>
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
      <PasswordField label="Password (at least 10 characters)" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={10} required />
      <ErrorNote error={a.error} />
      <button className="primary" disabled={a.busy}>{a.busy ? "Creating…" : "Create administrator"}</button>
    </AuthShell>
  );
}
