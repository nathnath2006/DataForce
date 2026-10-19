import { e, request, w } from "../api";
import type { MetricOut, ModelStatus } from "../flows/types";
import type { Source } from "../workbooks/types";

export type SavedKind = "linear" | "logistic" | "svm" | "svr" | "kmeans";

export interface SavedModel {
  id: string; name: string; kind: SavedKind; features: string[];
  metrics: { metrics: MetricOut[]; n_train: number | null; n_test: number | null; reasons: string[]; confusion: number[][] | null };
  status: ModelStatus; flow_id: string | null; node_id: string | null; created_at: string;
}

export interface ScoreResult {
  model_id: string; model_kind: SavedKind; status: ModelStatus; status_note: string | null;
  n_rows: number; n_scored: number;
  summary: { count: number; mean?: number | null; min?: number | null; max?: number | null; class_counts?: Record<string, number> | null };
  columns: string[]; rows: Record<string, unknown>[]; truncated_source: boolean; notes: string[];
}

export const modelApi = {
  list: (ws: string) => request<SavedModel[]>("GET", `${w(ws)}/models`),
  save: (ws: string, b: { flow_id: string; node_id: string; name: string }) =>
    request<SavedModel>("POST", `${w(ws)}/models`, b),
  rename: (ws: string, id: string, name: string) => request<SavedModel>("PATCH", `${w(ws)}/models/${e(id)}`, { name }),
  remove: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/models/${e(id)}`),
  score: (ws: string, id: string, source: Source) =>
    request<ScoreResult>("POST", `${w(ws)}/models/${e(id)}/score`, { source }),
};

export const KIND_LABEL: Record<SavedKind, string> = {
  linear: "Linear regression", logistic: "Logistic regression", svm: "SVM classifier", svr: "SVR", kmeans: "K-means",
};
