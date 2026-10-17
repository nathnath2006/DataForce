import { useSearchParams } from "react-router";
import { useState } from "react";
import { api } from "../api";
import { useWs } from "../context";
import { formatDateTime, isSafeAuthorizeUrl } from "../lib";
import { Confirm, ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";

const REASONS: Record<string, string> = {
  denied: "You denied access on the TamTam page.",
  expired: "The sign-in took too long (10 minutes). Try again.",
  invalid_state: "The sign-in could not be matched to this browser. Try again.",
  exchange_failed: "TamTam refused to issue a token. Try again.",
  server_error: "Something went wrong on the way back. Try again.",
};

export function SettingsPage() {
  const { ws } = useWs();
  const [sp] = useSearchParams();
  const c = useLoad(() => api.getConnector(ws.slug), [ws.slug]);
  const act = useAction();
  const [disc, setDisc] = useState(false);
  const [checked, setChecked] = useState<typeof c.data>(null);
  const d = checked ?? c.data;
  const result = sp.get("tamtam");
  const reason = sp.get("reason");

  const connect = () => act.run(async () => {
    const { authorize_url } = await api.connectTamtam(ws.slug);
    if (!isSafeAuthorizeUrl(authorize_url, d?.issuer)) {
      throw new Error("Refused: the sign-in address is not an https address on the TamTam issuer shown above.");
    }
    window.location.assign(authorize_url);
  });
  const check = () => act.run(async () => { setChecked(await api.checkTamtam(ws.slug)); });

  return (
    <section className="stack">
      <h1>Settings</h1>
      <h2>TamTam</h2>
      {result === "connected" && <div className="note ok" role="status">TamTam is connected.</div>}
      {result === "error" && <div className="note err" role="alert">TamTam connection failed. {REASONS[reason ?? ""] ?? "Try again."}</div>}
      <ErrorNote error={c.error} /><ErrorNote error={act.error} />
      {c.loading && !d ? <Loading /> : d && (
        <>
          {!d.secret_key_configured && (
            <div className="note warn" role="alert">
              No secret key is configured, so connecting is impossible. Run <code>make ui</code> (it creates the key) or <code>dataforce secrets init</code>.
            </div>
          )}
          {ws.is_demo && <p className="muted">This is a demo workspace: lookups always use the fake provider, never TamTam.</p>}
          <dl className="facts">
            <dt>Status</dt><dd><Tag kind={d.status === "connected" ? "ok" : d.status === "not_connected" ? "mute" : "warn"}>{d.status.replace("_", " ")}</Tag></dd>
            <dt>Lookups use</dt><dd>{d.enrichment_mode}</dd>
            <dt>Server</dt><dd className="pre">{d.resource}</dd>
            <dt>Issuer</dt><dd className="pre">{d.issuer ?? "—"}</dd>
            <dt>Scope</dt><dd>{d.scope ?? "—"}</dd>
            <dt>Connected</dt><dd>{formatDateTime(d.connected_at)}</dd>
            <dt>Token expires</dt><dd>{formatDateTime(d.token_expires_at)}</dd>
            <dt>Last check</dt><dd>{formatDateTime(d.checked_at)}</dd>
            {d.last_error && <><dt>Last error</dt><dd className="pre">{d.last_error}</dd></>}
            <dt>Pricing</dt>
            <dd>Email {d.pricing.email} credits · mobile {d.pricing.mobile} credits · ceiling {d.pricing.ceiling} per call
              {d.pricing.assumed && <> <Tag kind="warn">assumed, not confirmed</Tag></>}</dd>
          </dl>
          <div className="row wrap">
            <button className="primary" disabled={act.busy || !d.secret_key_configured || ws.is_demo} onClick={() => void connect()}>
              {d.status === "connected" ? "Reconnect TamTam" : "Connect TamTam"}
            </button>
            <button disabled={act.busy || d.status === "not_connected"} onClick={() => void check()}>Check connection</button>
            <button className="danger" disabled={act.busy || d.status === "not_connected"} onClick={() => setDisc(true)}>Disconnect</button>
          </div>
          {d.tools && (
            <div className="card">
              <h3>Tools offered by the server</h3>
              <p className="muted small">Only tools marked “allowed” can ever be called by DataForce. Descriptions come from the server and are shown as plain text.</p>
              <div className="tablewrap"><table>
                <thead><tr><th>Name</th><th>Description</th><th>Read-only</th><th>Destructive</th><th>Allowed</th></tr></thead>
                <tbody>{d.tools.map((t) => (
                  <tr key={t.name}>
                    <td className="pre">{t.name}</td><td className="pre">{t.description ?? "—"}</td>
                    <td>{t.read_only === null ? "?" : t.read_only ? "yes" : "no"}</td>
                    <td>{t.destructive === null ? "?" : t.destructive ? "yes" : "no"}</td>
                    <td>{t.allowed ? <Tag kind="ok">allowed</Tag> : <Tag kind="mute">not allowed</Tag>}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          )}
        </>
      )}
      {disc && (
        <Confirm title="Disconnect TamTam" confirmLabel="Disconnect" danger onClose={() => setDisc(false)}
          onConfirm={async () => { await api.disconnectTamtam(ws.slug); setChecked(null); c.reload(); }}>
          <p>The stored credential is deleted. Already stored emails and mobiles stay on their contacts.</p>
        </Confirm>
      )}
    </section>
  );
}
