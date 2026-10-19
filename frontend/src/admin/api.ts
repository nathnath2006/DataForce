import { q, request, w } from "../api";

export interface AdminTable { name: string; bytes: number; rows_estimate: number }
export interface AdminOverview {
  database: { size_bytes: number; size_mb: number; quota_mb: number; used_pct: number | null; tables: AdminTable[] };
  schema_status: { current: string | null; head: string | null; up_to_date: boolean };
  limits: { name: string; value: number; description: string }[];
}
export interface AdminRun {
  id: string; kind: string; status: string; started_at: string; finished_at: string | null;
  duration_ms: number | null; error: string | null; summary: string; stale: boolean;
}
export interface AdminUsage {
  source: string; days: number;
  rows: { provider: string; model: string; purpose: string; calls: number; failures: number; input_tokens: number; output_tokens: number }[];
  today: { purpose: string; calls: number; daily_cap: number | null }[];
}

export const adminApi = {
  overview: (ws: string) => request<AdminOverview>("GET", `${w(ws)}/admin/overview`),
  runs: (ws: string, kind: string, status: string) =>
    request<{ runs: AdminRun[] }>("GET", `${w(ws)}/admin/runs${q({ kind: kind || undefined, status: status || undefined, limit: 50 })}`),
  usage: (ws: string, days: number) => request<AdminUsage>("GET", `${w(ws)}/admin/ai-usage${q({ days })}`),
};
