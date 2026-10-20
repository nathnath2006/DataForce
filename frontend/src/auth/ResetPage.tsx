import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { AuthShell, PasswordField } from "./AuthShell";
import { useAuth } from "./context";

/** /reset?token=: choose a new password, then land in the app signed in. */
export function ResetPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { setMe } = useAuth();
  const nav = useNavigate();
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const a = useAction();
  const mismatch = again !== "" && pw !== again;
  const ok = token !== "" && pw.length >= 10 && pw === again;
  return (
    <AuthShell
      title="Choose a new password" subtitle="At least 10 characters."
      onSubmit={() => { if (ok && !a.busy) void a.run(async () => { setMe(await authApi.reset(token, pw)); nav("/", { replace: true }); }); }}
      footer={<Link className="auth-link" to="/forgot">Need a new link?</Link>}
    >
      <PasswordField label="New password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" autoFocus />
      <PasswordField label="Confirm password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" />
      {mismatch && <div className="note err" role="alert">The passwords do not match.</div>}
      {token === "" && <div className="note err" role="alert">This link is invalid or expired.</div>}
      <ErrorNote error={a.error} />
      <button className="primary" disabled={a.busy || !ok}>{a.busy ? "Saving…" : "Set password and sign in"}</button>
    </AuthShell>
  );
}
