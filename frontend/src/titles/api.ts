import { e, q, request, w } from "../api";

export interface NormalizeResult {
  run_id: string; n_contacts: number; by_source: Record<string, number>; n_flagged: number;
  llm_calls: number; ai_configured: boolean;
}
export interface ReviewItem {
  contact_id: string; full_name: string; account_id: string; account_name: string; title: string | null;
  function: string; seniority: string; source: string; flag: string | null;
}
export const FUNCTIONS = ["executive", "sales", "marketing", "finance", "operations", "tech", "hr", "unknown"] as const;
export const SENIORITIES = ["c_level", "vp", "head", "manager", "individual", "unknown"] as const;

export const titlesApi = {
  normalize: (ws: string, useAi: boolean) =>
    request<NormalizeResult>("POST", `${w(ws)}/titles/normalize`, { use_ai: useAi }),
  review: (ws: string, limit = 200) => request<ReviewItem[]>("GET", `${w(ws)}/titles/review${q({ limit })}`),
  setClass: (ws: string, contactId: string, b: { function: string; seniority: string }) =>
    request<ReviewItem>("PUT", `${w(ws)}/contacts/${e(contactId)}/title-class`, b),
};
