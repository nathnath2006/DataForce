import { useState } from "react";
import { useWs } from "../context";
import { label } from "../lib";
import { ErrorNote, emptyToNull, todayIso, useAction } from "../ui";
import type { DealOut } from "../types";
import { activityApi } from "./api";
import { STAGES, moveDateError } from "./logic";
import "./activity.css";

/** "Move to stage": where the deal is, with the date it got there. */
export function StageControl({ deal, onMoved }: { deal: DealOut; onMoved: () => void }) {
  const { ws } = useWs();
  const [stage, setStage] = useState<string>(deal.stage);
  const [date, setDate] = useState(todayIso());
  const [reason, setReason] = useState("");
  const act = useAction();
  const today = todayIso();
  const dateError = moveDateError(date, today, deal.created_on);
  const same = stage === deal.stage;
  const submit = async () => {
    const r = await act.run(() => activityApi.moveStage(ws.slug, deal.id, {
      stage, changed_on: date || null,
      lost_reason: stage === "closed_lost" ? emptyToNull(reason) : null,
    }));
    if (r) { setReason(""); onMoved(); }
  };
  return (
    <form className="stagebar" onSubmit={(ev) => { ev.preventDefault(); void submit(); }}>
      <label>Move to stage
        <select value={stage} onChange={(ev) => setStage(ev.target.value)}>
          {STAGES.map((s) => <option key={s} value={s}>{label(s)}{s === deal.stage ? " (current)" : ""}</option>)}
        </select>
      </label>
      <label>On
        <input type="date" value={date} min={deal.created_on} max={today} onChange={(ev) => setDate(ev.target.value)} />
      </label>
      {stage === "closed_lost" && (
        <label>Reason
          <input value={reason} maxLength={500} onChange={(ev) => setReason(ev.target.value)} placeholder="Why was it lost?" />
        </label>
      )}
      <button className="primary" type="submit" disabled={act.busy || same || !!dateError}>Move</button>
      {dateError && <p className="err">{dateError}</p>}
      <ErrorNote error={act.error} />
    </form>
  );
}
