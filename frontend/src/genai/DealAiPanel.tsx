import { useRef, useState } from "react";
import { formatDate } from "../lib";
import { AiBadge, ErrorNote, Modal, useAction } from "../ui";
import { genaiApi, type AiPreview, type Scope, type SummaryOut } from "./api";
import { capLeft, consentText } from "./logic";
import "./genai.css";

type Kind = "summary" | "tasks";

/** Opt-in AI on a deal (or an account): a cited summary and suggested tasks. Nothing is sent before
 *  the person confirms the dialog built from the preview. Suggested tasks land in the task list
 *  (call `onChanged` to reload it). Customer text is only ever rendered as text. */
export function DealAiPanel({ ws, dealId, accountId, onChanged }: {
  ws: string; dealId?: string; accountId?: string; onChanged?: () => void;
}) {
  const scope: Scope = dealId ? "deals" : "accounts";
  const id = (dealId ?? accountId) as string;
  const prev = useAction();
  const run = useAction();
  const [ask, setAsk] = useState<{ kind: Kind; preview: AiPreview } | null>(null);
  const [summary, setSummary] = useState<SummaryOut | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const open = async (kind: Kind) => {
    setInfo(null);
    const preview = await prev.run(() => genaiApi.preview(ws, scope, id));
    if (preview) setAsk({ kind, preview });
  };
  // a second click before the dialog closes must not send the text twice
  const sending = useRef(false);
  const confirm = async () => {
    if (!ask || sending.current) return;
    sending.current = true;
    const kind = ask.kind;
    setAsk(null);
    try {
      await send(kind);
    } finally {
      sending.current = false;
    }
  };
  const send = async (kind: Kind) => {
    if (kind === "summary") {
      const r = await run.run(() => genaiApi.summary(ws, scope, id));
      if (r) setSummary(r);
    } else {
      const r = await run.run(() => genaiApi.tasks(ws, scope, id));
      if (r) {
        setInfo(r.tasks.length === 0
          ? "No new task suggested."
          : `${r.tasks.length} task${r.tasks.length === 1 ? "" : "s"} suggested: accept or dismiss them in the task list.`);
        onChanged?.();
      }
    }
  };

  return (
    <section className="genai" aria-label="AI assistance">
      <div className="genai-actions">
        <button type="button" disabled={prev.busy || run.busy} onClick={() => void open("summary")}>Summarize with AI</button>
        <button type="button" disabled={prev.busy || run.busy} onClick={() => void open("tasks")}>Suggest tasks with AI</button>
      </div>
      <ErrorNote error={prev.error} />
      <ErrorNote error={run.error} />
      {run.busy && <p className="muted">Asking the model…</p>}
      {info && <p className="genai-note" role="status">{info}</p>}
      {summary && (
        <div className="genai-sum">
          <AiBadge>AI summary</AiBadge>
          {summary.sentences.length === 0 && <p className="muted">The model gave nothing that could be checked against your notes.</p>}
          {summary.sentences.map((s, i) => (
            <p key={i}>
              {s.text}
              {s.cites.map((c) => (
                <span key={c.item_id} className="genai-cite" title={c.origin_id}>{c.kind}, {formatDate(c.at)}</span>
              ))}
            </p>
          ))}
          <p className="genai-note">
            {summary.provider} {summary.model}. Every sentence cites its source; {summary.dropped} unchecked sentence{summary.dropped === 1 ? "" : "s"} dropped. Not saved.
          </p>
        </div>
      )}
      {ask && (
        <Modal title={ask.kind === "summary" ? "Summarize with AI" : "Suggest tasks with AI"} onClose={() => setAsk(null)}>
          <div className="stack genai-consent">
            <p>{consentText(ask.preview)}</p>
            <p className="genai-note">
              {capLeft(ask.preview)} of {ask.preview.daily_cap} AI calls left today. The result is labelled AI; numbers are never taken from the model.
            </p>
            <div className="row">
              <button type="button" className="ghost" onClick={() => setAsk(null)}>Cancel</button>
              <button type="button" disabled={ask.preview.n_items === 0 || capLeft(ask.preview) === 0} onClick={() => void confirm()}>
                Send and continue
              </button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
