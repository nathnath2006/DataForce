import { useState } from "react";
import { useWs } from "../context";
import { ErrorNote, emptyToNull, useAction } from "../ui";
import type { ContactOut, DealOut } from "../types";
import { activityApi } from "./api";
import { isFuture, toLocalInput } from "./logic";
import type { ActivityKind, Direction } from "./types";
import "./activity.css";

/** "Log a call / email / meeting": a compact form. */
export function ActivityPanel({ deal, contacts, onLogged }: { deal: DealOut; contacts: ContactOut[]; onLogged: () => void }) {
  const { ws, actingAs } = useWs();
  const [kind, setKind] = useState<ActivityKind>("call");
  const [direction, setDirection] = useState<Direction | "">("outbound");
  const [when, setWhen] = useState(() => toLocalInput(new Date()));
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [people, setPeople] = useState<string[]>([]);
  const act = useAction();
  const future = isFuture(when);
  const ok = subject.trim() !== "" && !future && when !== "";
  const submit = async () => {
    const r = await act.run(() => activityApi.createActivity(ws.slug, deal.account_id, {
      kind, direction: direction || null, occurred_at: new Date(when).toISOString(),
      subject: subject.trim(), body: emptyToNull(body), deal_id: deal.id,
      participant_ids: people, author_id: actingAs,
    }));
    if (r) { setSubject(""); setBody(""); setPeople([]); setWhen(toLocalInput(new Date())); onLogged(); }
  };
  const toggle = (id: string) => setPeople((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  return (
    <form className="actform" onSubmit={(ev) => { ev.preventDefault(); void submit(); }}>
      <label>Kind
        <select value={kind} onChange={(ev) => setKind(ev.target.value as ActivityKind)}>
          <option value="call">Call</option><option value="email">Email</option>
          <option value="meeting">Meeting</option><option value="other">Other</option>
        </select>
      </label>
      <label>Direction
        <select value={direction} onChange={(ev) => setDirection(ev.target.value as Direction | "")}>
          <option value="outbound">Outbound</option><option value="inbound">Inbound</option><option value="">None</option>
        </select>
      </label>
      <label>When
        <input type="datetime-local" value={when} max={toLocalInput(new Date())} onChange={(ev) => setWhen(ev.target.value)} />
      </label>
      <label className="wide">Subject
        <input value={subject} maxLength={300} onChange={(ev) => setSubject(ev.target.value)} placeholder="What was it about?" />
      </label>
      <label className="wide">Details (optional)
        <textarea rows={2} value={body} maxLength={10000} onChange={(ev) => setBody(ev.target.value)} />
      </label>
      {contacts.length > 0 && (
        <div className="wide people" role="group" aria-label="Participants">
          {contacts.map((c) => (
            <label key={c.id} className="check">
              <input type="checkbox" checked={people.includes(c.id)} onChange={() => toggle(c.id)} />{c.full_name}
            </label>
          ))}
        </div>
      )}
      {future && <p className="err wide">The time cannot be in the future.</p>}
      <div className="wide"><button className="primary" type="submit" disabled={!ok || act.busy}>Log it</button></div>
      <div className="wide"><ErrorNote error={act.error} /></div>
    </form>
  );
}
