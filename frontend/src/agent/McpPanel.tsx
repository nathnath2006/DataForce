// Owned by agent MS-UI (docs/M3A-CONTRACT.md section 5): connect an AI assistant over MCP.
import { useState } from "react";
import { request, w } from "../api";
import { useWs } from "../context";
import { formatDateTime } from "../lib";
import { ErrorNote, Loading, Tag, useLoad } from "../ui";
import { callSummary, desktopSnippet, shortDescription, type AgentInfo } from "./format";

function Snippet({ title, text }: { title: string; text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  };
  return (
    <div className="stack">
      <div className="row between">
        <strong>{title}</strong>
        <button onClick={() => void copy()}>{state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}</button>
      </div>
      <pre className="pre">{text}</pre>
    </div>
  );
}

export function McpPanel() {
  const { ws } = useWs();
  const info = useLoad(() => request<AgentInfo>("GET", `${w(ws.slug)}/agent`), [ws.slug]);
  const d = info.data;
  return (
    <div className="card stack">
      <div className="row between">
        <h2>AI assistants (MCP)</h2>
        <button onClick={() => info.reload()}>Refresh</button>
      </div>
      <p className="muted small">
        Connect Claude Desktop, Claude Code or another assistant on this computer to this workspace.
        It asks DataForce for exact counts and verified statistics; it cannot change anything.
      </p>
      <ErrorNote error={info.error} />
      {info.loading && !d && <Loading />}
      {d && (
        <>
          <Snippet title="Claude Desktop (claude_desktop_config.json)" text={desktopSnippet(d.connect)} />
          <Snippet title="Claude Code (terminal)" text={d.connect.claude_code} />
          <div className="stack">
            <strong>Tools</strong>
            {d.tools.length === 0 && <p className="muted small">No tools available yet.</p>}
            {d.tools.length > 0 && (
              <div className="tablewrap"><table>
                <tbody>{d.tools.map((t) => (
                  <tr key={t.name}>
                    <td><code>{t.name}</code></td>
                    <td className="small">{shortDescription(t.description)}</td>
                    <td>{t.read_only && <Tag kind="ok">read-only</Tag>}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </div>
          <div className="stack">
            <strong>Recent calls</strong>
            {d.recent_calls.length === 0 && <p className="muted small">No call yet.</p>}
            {d.recent_calls.map((c, i) => (
              <div key={i} className="small row between">
                <span>{callSummary(c)}</span>
                <span className="muted">{formatDateTime(c.at)}</span>
              </div>
            ))}
          </div>
        </>
      )}
      <p className="muted small">
        The assistant gets read access to this workspace only. It never sees emails, phone numbers or keys.
      </p>
    </div>
  );
}
