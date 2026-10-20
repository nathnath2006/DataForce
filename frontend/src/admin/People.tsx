import { useState } from "react";
import { api } from "../api";
import { authApi, type Member } from "../auth/api";
import { useAuth } from "../auth";
import { Confirm, Empty, ErrorNote, Field, Loading, Tag, useAction, useLoad } from "../ui";
import "../auth/auth.css";

/** Admin page section: who can sign in to this workspace, and with which rights. */
export function People({ slug }: { slug: string }) {
  const { user } = useAuth();
  const members = useLoad(() => authApi.members(slug), [slug]);
  const crm = useLoad(() => api.listUsers(slug), [slug]);
  const a = useAction();
  const [resetFor, setResetFor] = useState<Member | null>(null);
  const [removeFor, setRemoveFor] = useState<Member | null>(null);
  const [adding, setAdding] = useState(false);

  const act = (fn: () => Promise<unknown>) => void a.run(async () => { await fn(); members.reload(); });
  const linked = new Set((members.data ?? []).map((m) => m.app_user_id).filter(Boolean));

  return (
    <div className="card stack">
      <div className="row">
        <h2>People and access</h2>
        <button type="button" className="primary" onClick={() => setAdding(true)}>Add person</button>
      </div>
      <ErrorNote error={members.error} />
      <ErrorNote error={a.error} />
      {members.loading && !members.data ? <Loading /> : (members.data ?? []).length === 0 ? <Empty>No members yet.</Empty> : (
        <table className="people-table">
          <thead><tr><th>Person</th><th>Role</th><th>See all</th><th>Delete own</th><th>CRM identity</th><th /></tr></thead>
          <tbody>
            {(members.data ?? []).map((m) => {
              const self = m.user_id === user?.id;
              const locked = self || m.is_admin;
              return (
                <tr key={m.user_id}>
                  <td>{m.display_name}<div className="muted">{m.email}</div>{m.disabled && <Tag kind="bad">disabled</Tag>}</td>
                  <td>
                    <select value={m.role} disabled={locked} aria-label={`Role of ${m.display_name}`}
                      onChange={(e) => act(() => authApi.updateMember(slug, m.user_id, { role: e.target.value as "admin" | "rep" }))}>
                      <option value="rep">Rep</option><option value="admin">Admin</option>
                    </select>
                  </td>
                  <td><input type="checkbox" checked={m.see_all} aria-label="See all" onChange={(e) => act(() => authApi.updateMember(slug, m.user_id, { see_all: e.target.checked }))} /></td>
                  <td><input type="checkbox" checked={m.delete_own} aria-label="Delete own" onChange={(e) => act(() => authApi.updateMember(slug, m.user_id, { delete_own: e.target.checked }))} /></td>
                  <td>
                    <select value={m.app_user_id ?? ""} aria-label="CRM identity"
                      onChange={(e) => act(() => authApi.updateMember(slug, m.user_id, e.target.value ? { app_user_id: e.target.value } : { clear_app_user: true }))}>
                      <option value="">None</option>
                      {(crm.data ?? []).filter((u) => u.id === m.app_user_id || !linked.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
                    </select>
                  </td>
                  <td className="row end">
                    <button type="button" onClick={() => setResetFor(m)}>Reset password</button>
                    {!locked && (m.disabled
                      ? <button type="button" onClick={() => act(() => authApi.enable(slug, m.user_id))}>Enable</button>
                      : <button type="button" onClick={() => act(() => authApi.disable(slug, m.user_id))}>Disable</button>)}
                    {!locked && <button type="button" className="danger" onClick={() => setRemoveFor(m)}>Remove</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {adding && <AddPerson slug={slug} onClose={() => setAdding(false)} onDone={members.reload} linked={linked as Set<string>} />}
      {resetFor && <ResetPassword slug={slug} member={resetFor} onClose={() => setResetFor(null)} />}
      {removeFor && (
        <Confirm title="Remove from workspace" confirmLabel="Remove" danger onClose={() => setRemoveFor(null)}
          onConfirm={async () => { await authApi.remove(slug, removeFor.user_id); members.reload(); }}>
          <p>{removeFor.display_name} will no longer be able to open this workspace.</p>
        </Confirm>
      )}
    </div>
  );
}

function AddPerson(props: { slug: string; linked: Set<string>; onClose: () => void; onDone: () => void }) {
  const crm = useLoad(() => api.listUsers(props.slug), [props.slug]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "rep">("rep");
  const [crmId, setCrmId] = useState("");
  return (
    <Confirm title="Add person" confirmLabel="Add" onClose={props.onClose}
      onConfirm={async () => {
        await authApi.addMember(props.slug, {
          email, display_name: name || undefined, password, role, app_user_id: crmId || null,
        });
        props.onDone();
      }}>
      <p className="muted">Enter an existing email to add that account; otherwise a new one is created. An empty password is only allowed in demo workspaces on this computer.</p>
      <Field label="Email"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
      <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Password"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></Field>
      <Field label="Role">
        <select value={role} onChange={(e) => setRole(e.target.value as "admin" | "rep")}><option value="rep">Rep</option><option value="admin">Admin</option></select>
      </Field>
      <Field label="CRM identity">
        <select value={crmId} onChange={(e) => setCrmId(e.target.value)}>
          <option value="">None</option>
          {(crm.data ?? []).filter((u) => !props.linked.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
        </select>
      </Field>
    </Confirm>
  );
}

function ResetPassword(props: { slug: string; member: Member; onClose: () => void }) {
  const [password, setPassword] = useState("");
  return (
    <Confirm title={`Reset password for ${props.member.display_name}`} confirmLabel="Reset" onClose={props.onClose}
      onConfirm={() => authApi.resetPassword(props.slug, props.member.user_id, password)}>
      <Field label="New password (empty only in demo workspaces on this computer)">
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
      </Field>
    </Confirm>
  );
}
