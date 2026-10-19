import { e, request, w } from "../api";

// Mirrors backend/app/api/schemas_genai.py.
export interface AiPreview {
  n_items: number; n_chars: number; truncated: boolean; by_kind: Record<string, number>;
  provider: string; model: string; calls_today: number; daily_cap: number;
}
export interface Citation { item_id: string; kind: string; at: string; origin_id: string }
export interface SummaryOut {
  ai: boolean; provider: string; model: string; dropped: number;
  sentences: { text: string; cites: Citation[] }[];
}
export interface SuggestedTask { id: string; title: string; status: string; quote: string }
export interface ActionItemsOut {
  ai: boolean; provider: string; model: string; tasks: SuggestedTask[]; dropped: number; duplicates: number;
}
export type Scope = "deals" | "accounts";

export const genaiApi = {
  preview: (ws: string, scope: Scope, id: string) =>
    request<AiPreview>("GET", `${w(ws)}/${scope}/${e(id)}/ai/preview`),
  summary: (ws: string, scope: Scope, id: string) =>
    request<SummaryOut>("POST", `${w(ws)}/${scope}/${e(id)}/ai/summary`),
  tasks: (ws: string, scope: Scope, id: string) =>
    request<ActionItemsOut>("POST", `${w(ws)}/${scope}/${e(id)}/ai/tasks`),
};
