import { useState } from "react";
import { Link } from "react-router";
import { formatNum, formatPct } from "../lib";
import { Confirm, ErrorNote, Tag, useAction } from "../ui";
import { KIND_LABEL, modelApi, type SavedModel } from "./api";
import { ScoreNow } from "./ScoreNow";

const pct = new Set(["accuracy"]);
const fmt = (name: string, v: number | null | undefined) => (pct.has(name) ? formatPct(v ?? null) : formatNum(v ?? null, 3));

export function ModelCard({ slug, model, onChanged }: { slug: string; model: SavedModel; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(model.name);
  const [del, setDel] = useState(false);
  const act = useAction();
  const ok = model.status === "verified";
  const rename = async () => {
    const r = await act.run(() => modelApi.rename(slug, model.id, name.trim()));
    if (r) { setRenaming(false); onChanged(); }
  };
  return (
    <article className={`card md-card${ok ? "" : " nvbox"}`}>
      <div className="row between wrap">
        {renaming ? (
          <span className="row">
            <input aria-label="Model name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
            <button className="primary" disabled={!name.trim() || act.busy} onClick={rename}>Save</button>
            <button onClick={() => { setRenaming(false); setName(model.name); }}>Cancel</button>
          </span>
        ) : <h3>{model.name}</h3>}
        <span className="row">
          {ok ? <Tag kind="ok">verified</Tag> : <Tag kind="mute">{model.status === "exploratory" ? "exploratory" : "not verified"}</Tag>}
          <Tag>{KIND_LABEL[model.kind]}</Tag>
        </span>
      </div>
      <ErrorNote error={act.error} />
      <p className="muted small">
        Features: {model.features.join(", ")} · created {new Date(model.created_at).toLocaleDateString("en-GB")}
        {model.metrics.n_test != null && <> · train {model.metrics.n_train} · test {model.metrics.n_test}</>}
        {" · "}
        {model.flow_id
          ? <Link to={`/w/${slug}/analysis/${model.flow_id}`}>source flow</Link>
          : <span>source flow deleted</span>}
      </p>
      {model.metrics.metrics.length > 0 && (
        <div className="tablewrap"><table>
          <thead><tr><th>Metric (held-out)</th><th className="num">Value</th><th>95% CI</th><th className="num">Baseline</th></tr></thead>
          <tbody>{model.metrics.metrics.map((m) => (
            <tr key={m.name}>
              <td>{m.name}</td><td className="num">{fmt(m.name, m.value)}</td>
              <td>{m.ci_low != null && m.ci_high != null ? `${fmt(m.name, m.ci_low)} to ${fmt(m.name, m.ci_high)}` : ""}</td>
              <td className="num">{m.baseline != null ? fmt(m.name, m.baseline) : ""}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {!ok && model.metrics.reasons.length > 0 && (
        <ul className="reasons">{model.metrics.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      )}
      <div className="row wrap">
        <button className={open ? "" : "primary"} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Close" : "Score now"}</button>
        <button onClick={() => setRenaming(true)} disabled={renaming}>Rename</button>
        <button className="danger" onClick={() => setDel(true)}>Delete</button>
      </div>
      {open && <ScoreNow slug={slug} model={model} />}
      {del && (
        <Confirm title="Delete this model?" confirmLabel="Delete" danger onClose={() => setDel(false)}
          onConfirm={async () => { await modelApi.remove(slug, model.id); onChanged(); }}>
          <p>"{model.name}" is removed. A score block that uses it will fail until you pick another model.</p>
        </Confirm>
      )}
    </article>
  );
}
