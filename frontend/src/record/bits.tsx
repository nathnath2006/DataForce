import { useState } from "react";
import { api } from "../api";
import { useWs } from "../context";
import { todayIso, ErrorNote, Modal, useAction } from "../ui";

export const ico = (path: string) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>
);
export const ICONS = {
  edit: "M4 20h4L19 9l-4-4L4 16z", plus: "M12 5v14M5 12h14",
  trash: "M5 7h14M10 11v6M14 11v6M7 7l1 13h8l1-13M9 7V4h6v3", erase: "M6 6l12 12M18 6L6 18",
};

/** Minimal "New deal" on a known account (the owner is set by the server). */
export function NewDealDialog(p: { accountId: string; accountName: string; onClose: () => void; onSaved: () => void }) {
  const { ws } = useWs();
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const a = useAction();
  return (
    <Modal title={`New deal for ${p.accountName}`} onClose={p.onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        void a.run(async () => {
          await api.createDeal(ws.slug, {
            account_id: p.accountId, name: name.trim(), amount_eur: amount.trim() === "" ? null : amount.trim(),
            stage: "prospecting", created_on: todayIso(),
          });
          p.onSaved(); p.onClose();
        });
      }}>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={300} autoFocus /></label>
        <label>Amount (EUR)<input type="number" min={0} step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <ErrorNote error={a.error} />
        <div className="row end"><button type="button" onClick={p.onClose}>Cancel</button>
          <button className="primary" disabled={a.busy || name.trim() === ""}>Create</button></div>
      </form>
    </Modal>
  );
}
