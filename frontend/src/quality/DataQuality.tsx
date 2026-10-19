import { Link } from "react-router";
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
  const { ws } = useWs();
  const { data, error, loading } = useLoad(() => qualityApi.get(ws.slug), [ws.slug]);
  return (
    <section className="card dq" aria-labelledby="dq-title">
      <h2 id="dq-title">Data quality</h2>
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
