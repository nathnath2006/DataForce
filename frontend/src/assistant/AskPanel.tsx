import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useWs } from "../context";
import { ErrorNote, useAction, useLoad } from "../ui";
import { ApiError } from "../lib";
import type { AskOut, AskScope, AskTurn } from "../types";
import { aiApi } from "./api";
import { parseAnswer } from "./refs";
import { Icon } from "../icons";
import "./chat.css";

interface Turn { question: string; out: AskOut }

export function AnswerText({ out }: { out: AskOut }) {
  return (
    <p className="ask-answer">
      {parseAnswer(out.answer, out.citations).map((s, i) =>
        s.type === "text" ? <span key={i}>{s.text}</span> : (
          <span key={i} className={s.known ? "chip" : "chip unknown"} title={s.ref}>{s.label}</span>
        ))}
    </p>
  );
}

/** What an ask sends (shown above the question box). */
export function askNotice(target: string, provider: string): string {
  return `Your question and the CRM data of ${target}, including all its accounts' people with their titles, deals, notes, comments and meeting titles, are sent to ${provider}.`;
}

const SUGGESTIONS: Record<AskScope["kind"], string[]> = {
  account: ["Summarize this account", "Who decides, and who reports to whom?", "What is blocking the open deal?", "What happened in the last meetings?"],
  company: ["Summarize this company", "Which accounts are most active?", "Who are the key people?", "What did customers raise in meetings?"],
  deal: ["Summarize this deal", "What are the risks?", "Who is involved?", "What happened recently?"],
};

/** The assistant as a chat: messages scroll, the composer stays at the bottom. */
export function AskPanel({ scope, bare }: { scope: AskScope; bare?: boolean }) {
  const { ws } = useWs();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const a = useAction();
  const what = scope.kind;
  const info = useLoad(() => aiApi.scope(ws.slug, scope), [ws.slug, scope.kind, scope.id]);
  const target = info.data?.company_name ?? `this ${what === "company" ? "company" : "account"}`;
  const notConfigured = a.error instanceof ApiError && a.error.code === "connector_not_configured";
  const provider = turns.length ? turns[turns.length - 1]!.out.provider : "your configured AI provider";
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns.length, pending]);

  const ask = (raw?: string) => {
    const text = (raw ?? question).trim();
    if (!text || a.busy) return;
    const history: AskTurn[] = turns.slice(-5).flatMap((t): AskTurn[] => [
      { role: "user", content: t.question.slice(0, 4000) },
      { role: "assistant", content: t.out.answer.slice(0, 4000) },
    ]);
    setPending(text);
    setQuestion("");
    void a.run(async () => {
      try {
        const out = await aiApi.ask(ws.slug, { scope, question: text, history });
        setTurns((t) => [...t, { question: text, out }]);
      } catch (e) {
        setQuestion(text); // give the question back so nothing typed is lost
        throw e;
      } finally {
        setPending(null);
        box.current?.focus();
      }
    });
  };

  return (
    <div className={`chat${bare ? "" : " card"}`}>
      {!bare && <h2>Ask about this {what}</h2>}
      <div className="chat-log" aria-live="polite">
        {turns.length === 0 && !pending && (
          <div className="chat-empty">
            <span className="icon-badge"><Icon name="sparkle" /></span>
            <p>Ask anything about <strong>{target}</strong>. Answers cite the records they use.</p>
            <div className="chat-suggest">
              {SUGGESTIONS[scope.kind].map((s) => <button key={s} type="button" onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="chat-pair">
            <div className="bubble me"><p className="pre">{t.question}</p></div>
            <div className="bubble bot">
              <AnswerText out={t.out} />
              {t.out.unverified_numbers.length > 0 && (
                <div className="note warn" role="alert">
                  Numbers not found in the data: {t.out.unverified_numbers.join(", ")}. Treat them as unverified.
                </div>
              )}
              {(t.out.numbers_from_notes ?? []).length > 0 && (
                <div className="note" role="note">
                  Numbers taken from notes or comments (as written there, not verified):{" "}
                  {(t.out.numbers_from_notes ?? []).join(", ")}.
                </div>
              )}
              {t.out.quotes.length > 0 && (
                <ul className="plain">{t.out.quotes.map((qt, j) => (
                  <li key={j}>
                    {qt.verified ? <span className="tag ok">✓ verified</span> : <span className="tag warn">⚠ unverified</span>}{" "}
                    <q>{qt.text}</q> <span className="chip">{qt.ref}</span>
                  </li>
                ))}</ul>
              )}
              {t.out.truncated && <p className="muted small">Older notes were left out to fit the size limit.</p>}
              <p className="bubble-meta">{t.out.provider} · {t.out.model}</p>
            </div>
          </div>
        ))}
        {pending && (
          <div className="chat-pair">
            <div className="bubble me"><p className="pre">{pending}</p></div>
            <div className="bubble bot typing" aria-label="The assistant is answering"><span /><span /><span /></div>
          </div>
        )}
        <div ref={end} />
      </div>
      {notConfigured ? (
        <div className="note warn" role="alert">No AI model is set. <Link to={`/w/${ws.slug}/settings`}>Set an AI model in Settings</Link>.</div>
      ) : <ErrorNote error={a.error} />}
      <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <textarea ref={box} rows={1} maxLength={2000} value={question} aria-label="Your question"
          placeholder={`Ask about ${target}…`} onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(); } }} />
        <button className="primary send" aria-label="Send" disabled={a.busy || !question.trim()}><Icon name="send" size={18} /></button>
      </form>
      <details className="chat-notice">
        <summary>What is sent, and to whom</summary>
        <p>{askNotice(target, provider)} Answers can be wrong: check the cited facts. This conversation is kept on this page only.</p>
      </details>
    </div>
  );
}
