import { useState } from "react";
import { useWs } from "../context";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Tag, useAction, useLoad } from "../ui";
import { flowApi } from "./flowApi";
import type { ConnectionOut } from "./types";
import "./flows.css";

export function ConnectionsPanel() {
  const { ws } = useWs();
  const list = useLoad(() => flowApi.connections(ws.slug), [ws.slug]);
  const [editing, setEditing] = useState<ConnectionOut | "new" | null>(null);
  const [deleting, setDeleting] = useState<ConnectionOut | null>(null);
  const test = useAction();
  return (
    <div className="card stack">
      <div className="row between">
        <h2>Data connections</h2>
        <button onClick={() => setEditing("new")}>Add PostgreSQL connection</button>
      </div>
      <p className="muted small">Read-only access. Passwords are stored sealed and never shown again.</p>
      <ErrorNote error={list.error} />
      <ErrorNote error={test.error} />
      {list.loading && !list.data && <Loading />}
      {list.data?.length === 0 && <Empty>No connection yet.</Empty>}
      {list.data && list.data.length > 0 && (
        <div className="tablewrap"><table>
          <thead><tr><th>Name</th><th>Server</th><th>Last test</th><th /></tr></thead>
          <tbody>{list.data.map((c) => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td>{c.username}@{c.host}:{c.port}/{c.database} <span className="muted small">({c.sslmode})</span></td>
              <td>
                {c.last_test_ok === true && <Tag kind="ok">OK</Tag>}
                {c.last_test_ok === false && <Tag kind="bad">Failed</Tag>}
                {c.last_test_ok == null && <Tag kind="mute">Not tested</Tag>}
                {c.last_error && <div className="muted small">{String(c.last_error)}</div>}
              </td>
              <td className="row end">
                <button disabled={test.busy} onClick={() => void test.run(async () => { await flowApi.testConnection(ws.slug, c.id); list.reload(); })}>Test</button>
                <button onClick={() => setEditing(c)}>Edit</button>
                <button className="danger" onClick={() => setDeleting(c)}>Delete</button>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {editing && <ConnForm slug={ws.slug} conn={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); list.reload(); }} />}
      {deleting && (
        <Confirm title="Delete connection" confirmLabel="Delete" danger onClose={() => setDeleting(null)}
          onConfirm={async () => { await flowApi.deleteConnection(ws.slug, deleting.id); list.reload(); }}>
          <p>Delete <strong>{deleting.name}</strong>? Flows that use it will stop running.</p>
        </Confirm>
      )}
    </div>
  );
}

function ConnForm(props: { slug: string; conn: ConnectionOut | null; onClose: () => void; onDone: () => void }) {
  const c = props.conn;
  const [name, setName] = useState(c?.name ?? "");
  const [host, setHost] = useState(c?.host ?? "127.0.0.1");
  const [port, setPort] = useState(String(c?.port ?? 5432));
  const [database, setDatabase] = useState(c?.database ?? "");
  const [username, setUsername] = useState(c?.username ?? "");
  const [password, setPassword] = useState("");
  const [sslmode, setSslmode] = useState(c?.sslmode ?? "prefer");
  const a = useAction();
  const save = () => void a.run(async () => {
    const body = { name: name.trim(), host: host.trim(), port: Number(port), database: database.trim(), username: username.trim(), sslmode };
    const withPw = password ? { ...body, password } : body;
    if (c) await flowApi.updateConnection(props.slug, c.id, withPw);
    else await flowApi.createConnection(props.slug, withPw);
    setPassword("");
    props.onDone();
  });
  const valid = name.trim() && host.trim() && database.trim() && username.trim() && Number(port) > 0;
  return (
    <Modal title={c ? "Edit connection" : "New PostgreSQL connection"} onClose={props.onClose}>
      <form className="stack" onSubmit={(ev) => { ev.preventDefault(); save(); }} autoComplete="off">
        <Field label="Name"><input value={name} onChange={(ev) => setName(ev.target.value)} /></Field>
        <div className="row">
          <Field label="Host"><input value={host} onChange={(ev) => setHost(ev.target.value)} /></Field>
          <Field label="Port"><input type="number" value={port} onChange={(ev) => setPort(ev.target.value)} /></Field>
        </div>
        <Field label="Database"><input value={database} onChange={(ev) => setDatabase(ev.target.value)} /></Field>
        <Field label="User"><input value={username} onChange={(ev) => setUsername(ev.target.value)} /></Field>
        <Field label={c ? "Password (leave empty to keep the stored one)" : "Password"}>
          <input type="password" value={password} autoComplete="new-password" onChange={(ev) => setPassword(ev.target.value)} />
        </Field>
        <Field label="SSL mode">
          <select value={sslmode} onChange={(ev) => setSslmode(ev.target.value)}>
            {["disable", "prefer", "require", "verify-ca", "verify-full"].map((m) => <option key={m}>{m}</option>)}
          </select>
        </Field>
        <p className="muted small">A server that is not on this machine requires require, verify-ca or verify-full.</p>
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button className="primary" type="submit" disabled={a.busy || !valid}>Save</button>
        </div>
      </form>
    </Modal>
  );
}
