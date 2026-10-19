import { AnalysisTabs } from "./AnalysisTabs";

export function ModelsPage() {
  return (
    <section className="stack">
      <AnalysisTabs />
      <h1>Models</h1>
      <p className="muted empty">Saved models arrive in phase 2.</p>
    </section>
  );
}
