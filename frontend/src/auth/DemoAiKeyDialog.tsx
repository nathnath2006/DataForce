import { useState } from "react";
import { aiApi } from "../assistant/api";
import { useWs } from "../context";
import { ErrorNote, Modal, Tag, useAction, useLoad } from "../ui";
import { demoApi } from "./demoApi";
import type { DemoProvider } from "./demoTypes";

const FALLBACK: Record<DemoProvider, string[]> = {
  gemini: ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-2.5-flash"],
  anthropic: ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
};

/** The visitor's own AI key for this demo session. Never shown back; cleared after save. */
export function DemoAiKeyDialog({ onClose, onChanged }: { onClose: () => void; onChanged?: () => void }) {
  const { ws } = useWs();
  const cur = useLoad(() => demoApi.getKey().catch(() => null), []);
  const [provider, setProvider] = useState<DemoProvider>("gemini");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const listed = useLoad(() => aiApi.models(ws.slug, provider).then((r) => r.models).catch(() => [] as string[]), [ws.slug, provider]);
  const a = useAction();
  const models = listed.data && listed.data.length ? listed.data : FALLBACK[provider];
  const mdl = model || models[0] || "";
  const isSet = !!cur.data?.set;
  const save = () => a.run(async () => {
    await demoApi.putKey({ provider, model: mdl.trim(), api_key: key });
    setKey("");
    cur.reload();
    onChanged?.();
    onClose();
  });
  const remove = () => a.run(async () => { await demoApi.deleteKey(); cur.reload(); onChanged?.(); });
  return (
    <Modal title="Demo AI key" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); if (!a.busy && mdl && key.length >= 20) void save(); }}>
        <p className="muted">Use your own key: it stays in this demo session only and is deleted when you leave.</p>
        {isSet && <div className="row"><Tag kind="ok">A key is set: {cur.data?.provider} · {cur.data?.model}</Tag></div>}
        <label>Provider
          <select value={provider} onChange={(e) => { setProvider(e.target.value as DemoProvider); setModel(""); }}>
            <option value="gemini">Gemini</option><option value="anthropic">Anthropic</option>
          </select>
        </label>
        <label>Model
          <select value={mdl} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <label>API key (write-only)
          <input type="password" value={key} autoComplete="off" spellCheck={false} onChange={(e) => setKey(e.target.value)} />
        </label>
        <ErrorNote error={a.error} />
        <div className="row">
          <button className="primary" disabled={a.busy || !mdl || key.length < 20}>{a.busy ? "Saving…" : "Save key"}</button>
          {isSet && <button type="button" className="danger" disabled={a.busy} onClick={() => void remove()}>Remove key</button>}
          <button type="button" onClick={onClose}>Close</button>
        </div>
      </form>
    </Modal>
  );
}
