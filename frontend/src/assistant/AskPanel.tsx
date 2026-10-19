import { useState } from "react";
import { Link } from "react-router";
import { useWs } from "../context";
import { ErrorNote, useAction } from "../ui";
import { ApiError } from "../lib";
import type { AskOut, AskScope, AskTurn } from "../types";
import { aiApi } from "./api";
import { parseAnswer } from "./refs";

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

export function AskPanel({ scope, bare }: { scope: AskScope; bare?: boolean }) {
  const { ws } = useWs();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const a = useAction();
  const what = scope.kind === "account" ? "account" : "company";
  const notConfigured = a.error instanceof ApiError && a.error.code === "connector_not_configured";
  const provider = turns.length ? turns[turns.length - 1]!.out.provider : "your configured AI provider";

  const ask = () => {
    const text = question.trim();
    if (!text) return;
    const history: AskTurn[] = turns.slice(-5).flatMap((t): AskTurn[] => [
      { role: "user", content: t.question.slice(0, 4000) },
      { role: "assistant", content: t.out.answer.slice(0, 4000) },
    ]);
    void a.run(async () => {
      const out = await aiApi.ask(ws.slug, { scope, question: text, history });
      setTurns((t) => [...t, { question: text, out }]);
      setQuestion("");
    });
  };

  return (
    <div className={bare ? "stack" : "card stack"}>
      {!bare && <h2>Ask about this {what}</h2>}
      <p className="muted small">
        Your question and this {what}&apos;s CRM data (names, titles, deals, notes) are sent to {provider}.
        Answers can be wrong: check the cited facts.
      </p>
      {turns.map((t, i) => (
        <div key={i} className="stack">
          <div className="ask-turn user"><strong>You</strong><p className="pre">{t.question}</p></div>
          <div className="ask-turn">
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
            <p className="muted small">{t.out.provider} · {t.out.model}</p>
          </div>
        </div>
      ))}
      {notConfigured ? (
        <div className="note warn" role="alert">No AI model is set. <Link to={`/w/${ws.slug}/settings`}>Set an AI model in Settings</Link>.</div>
      ) : <ErrorNote error={a.error} />}
      <label>Your question
        <textarea rows={3} maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)} />
      </label>
      <div className="row between">
        <span className="muted small">This conversation is kept on this page only.</span>
        <button className="primary" disabled={a.busy || !question.trim()} onClick={ask}>{a.busy ? "Asking…" : "Ask"}</button>
      </div>
    </div>
  );
}
