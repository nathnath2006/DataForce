import { Link } from "react-router";
import { useState } from "react";
import { invalidate } from "../data/useQuery";
import { ErrorNote, Field, Modal, useAction, useLoad } from "../ui";
import { api } from "../api";
import { authApi } from "./api";
import { useAuth } from "./context";
import "./auth.css";

/** The user menu in the top bar (name, role, workspace, CRM identity for the admin, sign out). */
export function UserMenu() {
  const { user, membership, isAdmin, signOut, refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [joining, setJoining] = useState(false);
  if (!user) return null;
  const role = membership ? (membership.role === "admin" ? "Admin" : "Rep") : isAdmin ? "Admin" : "";
  return (
    <div className="user-menu">
      <button type="button" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {user.display_name}
      </button>
      {open && (
        <div className="pop" role="menu">
          <div><strong>{user.display_name}</strong><div className="muted">{user.email}</div></div>
          {membership && <div>{role} in {membership.workspace_name}</div>}
          {isAdmin && membership && (
            <IdentityPicker slug={membership.workspace_slug} current={membership.app_user_id} onChanged={() => void refresh()} />
          )}
          {membership && <Link to={`/w/${membership.workspace_slug}/me`} className="menu-link">My settings</Link>}
          <button type="button" onClick={() => { setOpen(false); setJoining(true); }}>Join a workspace</button>
          <button type="button" onClick={() => void signOut()}>Sign out</button>
        </div>
      )}
      {joining && <JoinDialog onClose={() => setJoining(false)} />}
    </div>
  );
}

/** Paste a join token (or the whole link) to add another workspace to this account. */
function JoinDialog({ onClose }: { onClose: () => void }) {
  const { refresh } = useAuth();
  const [text, setText] = useState("");
  const a = useAction();
  const go = () => a.run(async () => {
    const token = (text.includes("token=") ? new URL(text, window.location.origin).searchParams.get("token") : text)?.trim() ?? "";
    await authApi.join(token);
    await refresh();
    invalidate("/workspaces");
    onClose();
  });
  return (
    <Modal title="Join a workspace" onClose={onClose}>
      <div className="stack">
        <p className="muted">Paste the join code or link your workspace administrator gave you.</p>
        <label>Join code<input value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" spellCheck={false} autoFocus /></label>
        <ErrorNote error={a.error} />
        <div className="row">
          <button type="button" className="primary" disabled={a.busy || !text.trim()} onClick={() => void go()}>{a.busy ? "Joining…" : "Join"}</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </Modal>
  );
}

function IdentityPicker(props: { slug: string; current: string | null; onChanged: () => void }) {
  const users = useLoad(() => api.listUsers(props.slug), [props.slug]);
  const { user } = useAuth();
  const a = useAction();
  return (
    <Field label="CRM identity">
      <select
        value={props.current ?? ""} disabled={a.busy || !user}
        onChange={(e) => {
          const v = e.target.value;
          void a.run(async () => {
            await authApi.updateMember(props.slug, user!.id, v ? { app_user_id: v } : { clear_app_user: true });
            props.onChanged();
          });
        }}
      >
        <option value="">None</option>
        {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
      </select>
      <ErrorNote error={a.error} />
    </Field>
  );
}
