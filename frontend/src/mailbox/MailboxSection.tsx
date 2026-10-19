import { useState } from "react";
import { useSearchParams } from "react-router";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import { Confirm, ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";
import { mailboxApi } from "./api";
import { isSafeMailAuthorizeUrl, mailboxReason, statusKind, statusLabel } from "./logic";
import type { MailboxConnectionOut, MailboxStatusOut, MailboxSyncResultOut } from "./types";
import "./mailbox.css";

function ProviderCard({ c, onChange, lookback, max }: { c: MailboxConnectionOut; onChange: (s: MailboxStatusOut | null) => void; lookback: number; max: number }) {
  const { ws } = useWs();
  const act = useAction();
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [editing, setEditing] = useState(false);
  const [disc, setDisc] = useState(false);
  const [result, setResult] = useState<MailboxSyncResultOut | null>(null);
  const hasClient = c.client_source !== null;
  const showForm = !hasClient || editing;

  const save = () => act.run(async () => {
    onChange(await mailboxApi.setClient(ws.slug, c.provider, { client_id: clientId.trim(), client_secret: secret.trim() || null }));
    setClientId(""); setSecret(""); setEditing(false);
  });
  const connect = () => act.run(async () => {
    const { authorize_url } = await mailboxApi.connect(ws.slug, c.provider);
    if (!isSafeMailAuthorizeUrl(authorize_url, c.provider)) {
      throw new Error(`Refused: the sign-in address is not an https address on ${c.label}'s own sign-in host.`);
    }
    window.location.assign(authorize_url);
  });
  const sync = () => act.run(async () => {
    setResult(await mailboxApi.sync(ws.slug, c.provider));
    onChange(await mailboxApi.status(ws.slug));
  });

  return (
    <div className="card stack mb-card">
      <div className="row wrap"><h3>{c.label}</h3><Tag kind={statusKind(c.status)}>{statusLabel(c.status)}</Tag></div>
      <ErrorNote error={act.error} />
      {c.status === "needs_reconnect" && <div className="note warn" role="alert">{c.label} no longer accepts the stored access. Reconnect it.</div>}
      {showForm ? (
        <div className="stack">
          <p className="muted small">Register your own OAuth client (see docs/MAILBOX-SETUP.md), with this redirect address:</p>
          <code className="pre">{c.redirect_uri}</code>
          <label>Client id
            <input value={clientId} autoComplete="off" spellCheck={false} onChange={(ev) => setClientId(ev.target.value)} />
          </label>
          <label>Client secret (write-only, never shown again)
            <input type="password" value={secret} autoComplete="off" spellCheck={false} onChange={(ev) => setSecret(ev.target.value)} />
          </label>
          <div className="row wrap">
            <button className="primary" disabled={act.busy || !clientId.trim() || !c.secret_key_configured} onClick={() => void save()}>Save client</button>
            {editing && <button onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </div>
      ) : (
        <p className="small">OAuth client: <Tag kind="ok">{c.client_source === "env" ? "from the environment" : "stored, sealed"}</Tag>{" "}
          <button className="link" onClick={() => setEditing(true)}>Replace</button></p>
      )}
      {!c.secret_key_configured && <div className="note warn" role="alert">No secret key is configured. Run <code>dataforce secrets init</code>.</div>}
      <dl className="facts">
        <dt>Account</dt><dd>{c.account_email ?? "—"}</dd>
        <dt>Last sync</dt><dd>{formatDateTime(c.last_sync_at)}</dd>
        <dt>Stored emails</dt>
        <dd>{c.counts.suggested} suggested · {c.counts.unmatched} unmatched · {c.counts.linked} linked · {c.counts.ignored} ignored</dd>
        {c.last_error && <><dt>Last error</dt><dd className="pre">{c.last_error}</dd></>}
      </dl>
      {result && (
        <div className="note ok" role="status">
          Read {result.fetched} emails, kept {result.candidates} (new: {result.new}, with a suggested deal: {result.suggested}).
          {result.errors.map((er) => <div key={er}>{er}</div>)}
        </div>
      )}
      <div className="row wrap">
        <button className="primary" disabled={act.busy || !hasClient || !c.secret_key_configured} onClick={() => void connect()}>
          {c.status === "connected" ? `Reconnect ${c.label}` : `Connect ${c.label}`}
        </button>
        <button disabled={act.busy || c.status !== "connected"} onClick={() => void sync()}>Sync now</button>
        <button className="danger" disabled={act.busy || c.status === "not_configured" || c.status === "configured"} onClick={() => setDisc(true)}>Disconnect</button>
      </div>
      <p className="muted small">Each sync reads the last {lookback} days, at most {max} emails.</p>
      {disc && (
        <Confirm title={`Disconnect ${c.label}`} confirmLabel="Disconnect" danger onClose={() => setDisc(false)}
          onConfirm={async () => { await mailboxApi.disconnect(ws.slug, c.provider); setResult(null); onChange(await mailboxApi.status(ws.slug)); }}>
          <p>The access is forgotten (and revoked at {c.label} when possible) and every stored email that is not linked to a deal is deleted. Linked emails stay on their deals as activities.</p>
        </Confirm>
      )}
    </div>
  );
}

/** Settings > Mailbox: Gmail and Outlook, read-only. */
export function MailboxSection() {
  const { ws } = useWs();
  const [sp] = useSearchParams();
  const s = useLoad(() => mailboxApi.status(ws.slug), [ws.slug]);
  const [state, setState] = useState<MailboxStatusOut | null>(null);
  const d = state ?? s.data;
  const result = sp.get("mailbox");
  return (
    <>
      <h2>Mailbox</h2>
      {result === "connected" && <div className="note ok" role="status">Mailbox connected.</div>}
      {result === "error" && <div className="note err" role="alert">Mailbox connection failed. {mailboxReason(sp.get("reason"))}</div>}
      <ErrorNote error={s.error} />
      <div className="note mb-privacy" role="note">
        <strong>What DataForce reads and keeps</strong>
        <ul>
          <li>Read-only access: Gmail <code>gmail.readonly</code>, or Outlook <code>Mail.Read</code>. It can never send, change or delete mail.</li>
          <li>It reads sender, recipients, date, subject and a snippet (200 characters at most), and the message and thread ids.</li>
          <li>It stores only emails where someone is a known contact or on an account's company domain (not a free webmail). Everything else is dropped in memory.</li>
          <li>An email body is read only when you link that email to a deal; it is converted to text, cut at 10,000 characters and kept only as the deal activity.</li>
          <li>Access tokens, the client secret and your address are stored encrypted and are never shown or logged.</li>
          <li>Erasing a contact deletes the stored emails that name them. Disconnecting deletes the access and the unlinked emails.</li>
        </ul>
      </div>
      {s.loading && !d ? <Loading /> : d && (
        <div className="mb-cards">
          {d.connections.map((c) => (
            <ProviderCard key={c.provider} c={c} onChange={(n) => (n ? setState(n) : s.reload())} lookback={d.lookback_days} max={d.max_messages} />
          ))}
        </div>
      )}
    </>
  );
}
