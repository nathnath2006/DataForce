import { useState } from "react";
import { adminApi } from "./api";
import type { CreationCodeCreated, CreationCodeOut, JoinTokenCreated, JoinTokenOut } from "../api.gen";
import { formatDateTime } from "../lib";
import { Empty, ErrorNote, Field, Loading, Tag, useAction, useLoad } from "../ui";

type Item = CreationCodeOut | JoinTokenOut;

function state(i: Item): { kind: "ok" | "mute" | "bad"; text: string } {
  if (i.status === "revoked") return { kind: "bad", text: "revoked" };
  if (i.status === "expired") return { kind: "mute", text: "expired" };
  if (i.status === "used_up") return { kind: "mute", text: "used up" };
  return { kind: "ok", text: "active" };
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" onClick={() => { void navigator.clipboard?.writeText(text).then(() => setDone(true), () => setDone(false)); }}>
      {done ? "Copied" : label}
    </button>
  );
}

/** Admin page section: creation codes (superadmin) and join tokens (workspace admin). */
export function AccessCodes({ ws, superadmin }: { ws: string; superadmin: boolean }) {
  return (
    <>
      {superadmin && <CreationCodes />}
      <JoinTokens ws={ws} />
    </>
  );
}

function CreationCodes() {
  const list = useLoad(() => adminApi.creationCodes(), []);
  const [label, setLabel] = useState("");
  const [days, setDays] = useState("14");
  const [uses, setUses] = useState("1");
  const [shown, setShown] = useState<CreationCodeCreated | null>(null);
  const a = useAction();
  const create = () => void a.run(async () => {
    setShown(await adminApi.createCode({ label: label.trim(), expires_in_days: Number(days), max_uses: Number(uses) }));
    setLabel(""); list.reload();
  });
  return (
    <div className="card stack">
      <h2>Creation codes</h2>
      <p className="muted small">A creation code lets one person sign up and start their own workspace. It is shown once.</p>
      <div className="row wrap">
        <Field label="Label"><input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} /></Field>
        <Field label="Valid for (days)"><input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} /></Field>
        <Field label="Uses"><input type="number" min={1} max={50} value={uses} onChange={(e) => setUses(e.target.value)} /></Field>
        <button type="button" className="primary" disabled={a.busy || !label.trim()} onClick={create}>Create code</button>
      </div>
      <ErrorNote error={a.error} />
      {shown?.code && (
        <div className="note" role="status">
          <p>Copy this code now. It is not shown again.</p>
          <p className="row"><code>{shown.code}</code><CopyButton text={shown.code} label="Copy code" /></p>
        </div>
      )}
      <ItemTable list={list} onRevoke={(id) => adminApi.revokeCode(id)} />
    </div>
  );
}

function JoinTokens({ ws }: { ws: string }) {
  const list = useLoad(() => adminApi.joinTokens(ws), [ws]);
  const [label, setLabel] = useState("");
  const [role, setRole] = useState<"rep" | "admin">("rep");
  const [days, setDays] = useState("7");
  const [uses, setUses] = useState("1");
  const [email, setEmail] = useState("");
  const [shown, setShown] = useState<JoinTokenCreated | null>(null);
  const a = useAction();
  const create = () => void a.run(async () => {
    setShown(await adminApi.createToken(ws, {
      role, label: label.trim(), expires_in_days: Number(days), max_uses: Number(uses), ...(email.trim() ? { email_to: email.trim() } : {}),
    }));
    setLabel(""); setEmail(""); list.reload();
  });
  const link = shown?.link ?? "";
  return (
    <div className="card stack">
      <h2>Join links</h2>
      <p className="muted small">A join link lets a person sign up into this workspace with the role you choose. It is shown once.</p>
      <div className="row wrap">
        <Field label="Label"><input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} /></Field>
        <Field label="Role"><select value={role} onChange={(e) => setRole(e.target.value as "rep" | "admin")}><option value="rep">Rep</option><option value="admin">Admin</option></select></Field>
        <Field label="Valid for (days)"><input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} /></Field>
        <Field label="Uses"><input type="number" min={1} max={50} value={uses} onChange={(e) => setUses(e.target.value)} /></Field>
        <Field label="Email the link to (optional)"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <button type="button" className="primary" disabled={a.busy || !label.trim()} onClick={create}>Create link</button>
      </div>
      <ErrorNote error={a.error} />
      {shown?.token && (
        <div className="note" role="status">
          <p>Copy this now. It is not shown again.{shown.email_queued ? " The link is also being emailed." : ""}</p>
          <p className="row wrap"><code>{link}</code><CopyButton text={link} label="Copy link" /><CopyButton text={shown.token} label="Copy code only" /></p>
        </div>
      )}
      <ItemTable list={list} onRevoke={(id) => adminApi.revokeToken(ws, id)} />
    </div>
  );
}

function ItemTable<I extends Item>({ list, onRevoke }: { list: { data: I[] | null; loading: boolean; error: unknown; reload: () => void }; onRevoke: (id: string) => Promise<unknown> }) {
  const a = useAction();
  if (list.loading && !list.data) return <Loading />;
  const rows = list.data ?? [];
  return (
    <>
      <ErrorNote error={list.error} /><ErrorNote error={a.error} />
      {rows.length === 0 ? <Empty>None yet.</Empty> : (
        <div className="tablewrap"><table>
          <thead><tr><th>Label</th>{"role" in rows[0]! && <th>Role</th>}<th className="num">Uses</th><th>Expires</th><th>State</th><th /></tr></thead>
          <tbody>{rows.map((r) => {
            const st = state(r);
            return (
              <tr key={r.id}>
                <td>{r.label}</td>{"role" in r && <td>{r.role}</td>}
                <td className="num">{r.uses} of {r.max_uses}</td><td>{formatDateTime(r.expires_at)}</td>
                <td><Tag kind={st.kind}>{st.text}</Tag></td>
                <td>{st.text === "active" && <button type="button" className="danger" disabled={a.busy} onClick={() => void a.run(async () => { await onRevoke(r.id); list.reload(); })}>Revoke</button>}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
      )}
    </>
  );
}
