import { useState } from "react";
import { Link } from "react-router";
import { useSeesAll } from "../auth";
import { useWs } from "../context";
import { ErrorNote, Loading, useLoad } from "../ui";
import { qualityApi, type QualityCheck } from "./api";
import { HealthBar } from "./HealthBar";

/** Where each problem is fixed (relative to the workspace). */
const FIX: Record<QualityCheck["id"], { to: string; text: string }> = {
  titles: { to: "../contacts", text: "Fix in Contacts" },
  managers: { to: "../accounts", text: "Open an account's org chart" },
  amounts: { to: "../deals", text: "Fix in Deals" },
  companies: { to: "../companies", text: "Fix in Companies" },
};

export function DataQualityCard() {
  const { ws, users } = useWs();
  const seesAll = useSeesAll();
  const [owner, setOwner] = useState("");
  const { data, error, loading } = useLoad(() => qualityApi.get(ws.slug, owner || undefined), [ws.slug, owner]);
  return (
    <section className="card dq" aria-labelledby="dq-title">
      <div className="row between wrap">
        <h2 id="dq-title">Data quality</h2>
        {seesAll && (
          <select aria-label="Sales rep" value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Everyone</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
        )}
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : data && (
        <div className="dq-grid">
          {data.checks.map((c) => (
            <div key={c.id} className="dq-item">
              <HealthBar label={c.label} total={c.total} segments={c.segments} />
              <Link className="small" to={FIX[c.id].to} relative="path">{FIX[c.id].text}</Link>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
