import { useState } from "react";
import { ErrorNote, Field, useAction, useLoad } from "../ui";
import { api } from "../api";
import { authApi } from "./api";
import { useAuth } from "./context";
import "./auth.css";

/** The user menu in the top bar (name, role, workspace, CRM identity for the admin, sign out). */
export function UserMenu() {
  const { user, membership, isAdmin, signOut, refresh } = useAuth();
  const [open, setOpen] = useState(false);
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
          <button type="button" onClick={() => void signOut()}>Sign out</button>
        </div>
      )}
    </div>
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
