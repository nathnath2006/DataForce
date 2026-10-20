import { useSearchParams } from "react-router";
import { useState } from "react";
import { api } from "../api";
import { aiApi } from "../assistant/api";
import { ConnectionsPanel } from "../flows/ConnectionsPanel";
import { McpPanel } from "../agent/McpPanel";
import { MailboxSection } from "../mailbox";
import type { AiProvider } from "../types";
import { useWs } from "../context";
import { DemoAiKeyCard, DemoBlockedNote, useAuth } from "../auth";
import { formatDateTime, isSafeAuthorizeUrl, tamtamReason } from "../lib";
import { meetingOrgNotice } from "../orgchart/model";
import { Confirm, ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";
import { Icon, type IconName } from "../icons";
import "./settings.css";

type TabKey = "integrations" | "ai" | "data" | "assistants";
const TABS: { key: TabKey; label: string; icon: IconName; hint: string }[] = [
  { key: "integrations", label: "Mail & TamTam", icon: "plug", hint: "The workspace mailbox and contact lookups" },
  { key: "ai", label: "AI model", icon: "sparkle", hint: "The model the assistant and AI features use" },
  { key: "data", label: "Data connections", icon: "dataset", hint: "Read-only databases for analysis flows" },
  { key: "assistants", label: "AI assistants", icon: "robot", hint: "Claude Desktop, Claude Code and other MCP clients" },
];

export function SettingsPage() {
  const [sp, setSp] = useSearchParams();
  // The TamTam sign-in comes back with ?tamtam=…: open its tab.
  const raw = sp.get("tab") ?? "integrations";
  const tab: TabKey = TABS.some((t) => t.key === raw) ? (raw as TabKey) : "integrations";
  const current = TABS.find((t) => t.key === tab)!;
  const { isDemo } = useAuth();
  return (
    <section className="stack">
      <div className="page-head">
        <div><h1>Settings</h1><p className="muted">{current.hint}.</p></div>
      </div>
      <div className="settings">
        <nav className="settings-nav tile soft" aria-label="Settings sections">
          {TABS.map((t) => (
            <button key={t.key} type="button" aria-current={t.key === tab ? "page" : undefined}
              className={t.key === tab ? "on" : ""} onClick={() => setSp({ tab: t.key })}>
              <Icon name={t.icon} size={18} />{t.label}
            </button>
          ))}
        </nav>
        <div className="stack settings-body">
                    {tab === "integrations" && (isDemo ? <DemoBlockedNote title="Mail & TamTam" /> : <><section className="tile"><MailboxSection /></section><TamtamSection /></>)}
          {tab === "ai" && (isDemo ? <DemoAiKeyCard /> : <AiSection />)}
          {tab === "data" && (isDemo ? <DemoBlockedNote title="Data connections" /> : <ConnectionsPanel />)}
          {tab === "assistants" && <McpPanel />}
        </div>
      </div>
    </section>
  );
}

function TamtamSection() {
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
    <section className="tile">
      <h2 className="tile-title"><Icon name="plug" />TamTam</h2>
      <p className="muted small">Contact lookups (emails, mobiles) for this workspace. Paid lookups only happen when someone clicks Enrich and confirms the credits.</p>
      {result === "connected" && <div className="note ok" role="status">TamTam is connected.</div>}
      {result === "error" && <div className="note err" role="alert">TamTam connection failed. {tamtamReason(reason)}</div>}
      <ErrorNote error={c.error} /><ErrorNote error={act.error} />
      {c.loading && !d ? <Loading /> : d && (
        <>
          {!d.secret_key_configured && (
            <div className="note warn" role="alert">
              No secret key is configured, so connecting is impossible. Run <code>make ui</code> (it creates the key) or <code>dataforce secrets init</code>.
            </div>
          )}
          {ws.is_demo && (
            <div className="note warn" role="note">
              <p><strong>TamTam is connected per workspace, and demo workspaces never use it</strong>: their people are
                fictional, so lookups here always use the fake provider and spend no credits.</p>
              <p>To connect TamTam, create a real workspace with the workspace menu (top left, <em>+ New workspace…</em>),
                then open its Settings.</p>
            </div>
          )}
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

const OTHER = "__other__";

function AiSection() {
  const { ws } = useWs();
  const s = useLoad(() => aiApi.get(ws.slug), [ws.slug]);
  const act = useAction();
  const [provider, setProvider] = useState<AiProvider | "">("");
  const listed = useLoad(() => aiApi.models(ws.slug, provider || undefined).catch(() => null), [ws.slug, provider]);
  const [model, setModel] = useState("");
  const [custom, setCustom] = useState(false);
  const [key, setKey] = useState("");
  const [replace, setReplace] = useState(false);
  const [state, setState] = useState<typeof s.data>(null);
  const d = state ?? s.data;
  if (s.loading && !d) return <Loading />;
  if (!d) return <ErrorNote error={s.error} />;
  const prov: AiProvider = provider || d.provider || "gemini";
  // The provider's own list (for the key this workspace stores) when it covers this provider; else the built-in suggestions.
  const fromProvider = listed.data && listed.data.provider === prov ? listed.data.models : [];
  const suggestions = fromProvider.length ? fromProvider : d.suggested_models[prov] ?? [];
  const preferred = prov === "gemini" && suggestions.includes("gemini-3.5-flash") ? "gemini-3.5-flash" : suggestions[0] ?? "";
  const mdl = model || (d.provider === prov ? d.model ?? "" : preferred);
  const showCustom = custom || (mdl !== "" && !suggestions.includes(mdl));
  const keyStored = d.configured && d.provider === prov;
  const needKey = !keyStored || replace;

  const save = () => act.run(async () => {
    setState(await aiApi.put(ws.slug, { provider: prov, model: mdl.trim(), ...(key ? { api_key: key } : {}) }));
    setKey(""); setReplace(false);
  });
  return (
    <section className="tile">
      <h2 className="tile-title"><Icon name="sparkle" />AI model</h2>
      <ErrorNote error={act.error} />
      <div className="note" role="note">{d.data_notice}</div>
      <div className="stack">
        <div className="grid2">
          <label>Provider
            <select value={prov} onChange={(e) => { setProvider(e.target.value as AiProvider); setModel(""); setCustom(false); }}>
              <option value="gemini">Gemini</option><option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label>Model
            <select value={showCustom ? OTHER : mdl}
              onChange={(e) => { if (e.target.value === OTHER) { setCustom(true); setModel(""); } else { setCustom(false); setModel(e.target.value); } }}>
              {suggestions.map((m) => <option key={m} value={m}>{m}</option>)}
              <option value={OTHER}>other…</option>
            </select>
          </label>
        </div>
        {showCustom && (
          <label>Model name
            <input value={mdl} pattern="[a-z0-9][a-z0-9.\-]{0,63}" onChange={(e) => setModel(e.target.value)} autoComplete="off" />
          </label>
        )}
        {keyStored && !replace ? (
          <div className="row"><Tag kind="ok">A key is stored</Tag>
            <button className="link" onClick={() => setReplace(true)}>Replace key</button></div>
        ) : (
          <label>API key (write-only, never shown again)
            <input type="password" value={key} autoComplete="off" spellCheck={false} onChange={(e) => setKey(e.target.value)} />
          </label>
        )}
        <div className="row wrap">
          <button className="primary" disabled={act.busy || !mdl.trim() || (needKey && key.length < 20)} onClick={() => void save()}>Save</button>
          <button disabled={act.busy || !d.configured} onClick={() => void act.run(async () => { setState(await aiApi.test(ws.slug)); })}>Test</button>
          <button className="danger" disabled={act.busy || !d.configured}
            onClick={() => void act.run(async () => { await aiApi.remove(ws.slug); setState(null); setKey(""); setReplace(false); s.reload(); })}>Remove</button>
        </div>
        <label className="check">
          <input type="checkbox" checked={d.allow_meeting_org} disabled={act.busy || !d.configured || !d.model}
            onChange={(e) => void act.run(async () => { setState(await aiApi.setMeetingOrg(ws.slug, e.target.checked)); })} />
          <span>
            Read meeting sentences for org statements
            <span className="muted small"> {meetingOrgNotice(d.provider, d.model)}</span>
          </span>
        </label>
        {d.last_test_at && (
          <p className="small">Last test {formatDateTime(d.last_test_at)}: {d.last_test_ok
            ? <Tag kind="ok">worked</Tag> : <Tag kind="bad">failed</Tag>}{d.last_error ? <span className="pre"> {d.last_error}</span> : null}</p>
        )}
      </div>
    </section>
  );
}
