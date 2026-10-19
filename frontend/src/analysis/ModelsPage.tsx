import { useWs } from "../context";
import { ModelCard } from "../models/ModelCard";
import { modelApi } from "../models/api";
import "../models/models.css";
import { Empty, ErrorNote, Loading, useLoad } from "../ui";
import { AnalysisTabs } from "./AnalysisTabs";

export function ModelsPage() {
  const { ws } = useWs();
  const models = useLoad(() => modelApi.list(ws.slug), [ws.slug]);
  return (
    <section className="stack">
      <AnalysisTabs />
      <h1>Models</h1>
      <p className="muted">A saved model keeps the parameters of a model block, not its training data, except an RBF SVM, which keeps up to 2,000 training rows as numbers to score with (said when you save it). It is verified only if it beat its baseline on held-out data; its scores take that status.</p>
      <ErrorNote error={models.error} />
      {models.loading && !models.data && <Loading />}
      {models.data?.length === 0 && <Empty>No saved model yet. Run a model block in a flow and choose Save model in its result.</Empty>}
      <div className="md-list">
        {(models.data ?? []).map((m) => <ModelCard key={m.id} slug={ws.slug} model={m} onChanged={models.reload} />)}
      </div>
    </section>
  );
}
