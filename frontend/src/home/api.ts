import { q, request, w } from "../api";

// Mirrors backend/app/api/schemas_home.py (Decimals travel as strings).
export interface HomeKpis {
  open_deals: number; open_pipeline_eur: string; won_this_quarter: number; won_this_quarter_eur: string;
  tasks_due_week: number; tasks_overdue: number;
}
export interface HomeDeal {
  id: string; name: string; account_id: string; account_name: string; stage: string;
  amount_eur: string | null; created_on: string; owner_name: string | null;
}
export interface HomeTask {
  id: string; title: string; due_on: string | null; status: string; overdue: boolean;
  deal_id: string | null; deal_name: string | null; account_id: string | null; account_name: string | null;
}
export interface HomeActivity {
  id: string; kind: string; at: string; title: string; author_name: string | null; deal_id: string; deal_name: string;
}
export interface HomeOut { kpis: HomeKpis; open_deals: HomeDeal[]; tasks: HomeTask[]; activity: HomeActivity[] }

export const homeApi = {
  get: (ws: string, owner?: string, signal?: AbortSignal) =>
    request<HomeOut>("GET", `${w(ws)}/home${q({ owner })}`, undefined, signal),
};
