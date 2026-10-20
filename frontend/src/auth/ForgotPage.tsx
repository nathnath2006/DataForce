import { useState } from "react";
import { Link } from "react-router";
import { ErrorNote, useAction } from "../ui";
import { authApi } from "./api";
import { AuthShell } from "./AuthShell";

/** /forgot: emails a reset link. */
export function ForgotPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const a = useAction();
  return (
    <AuthShell
      title="Forgot password" subtitle="Enter your email. We email you a link to choose a new password."
      onSubmit={() => { if (email.trim() && !a.busy) void a.run(async () => { await authApi.forgot(email); setSent(true); }); }}
      footer={<Link className="auth-link" to="/login">Back to sign in</Link>}
    >
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus /></label>
      <ErrorNote error={a.error} />
      {sent && (
        <div className="note" role="status">
          If an account exists for this email, we sent a link. It works for 15 minutes. Your administrator can also reset your password in Admin, People and access.
        </div>
      )}
      <button className="primary" disabled={a.busy || email.trim() === ""}>{a.busy ? "Sending…" : "Send reset link"}</button>
    </AuthShell>
  );
}
