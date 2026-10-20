import { e, q, request, w } from "../api";
import type * as G from "../api.gen";

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
  limits: (ws: string | null) => request<G.EditableLimit[]>("GET", ws ? `${w(ws)}/admin/limits` : "/admin/limits"),
  setLimit: (ws: string | null, key: string, value: number | null) =>
    request<G.EditableLimit>("PUT", `${ws ? `${w(ws)}/admin/limits` : "/admin/limits"}/${e(key)}`, { value } satisfies G.LimitUpdate),
  usageReport: (ws: string, days: number) =>
    request<G.UsageReport>("GET", `${w(ws)}/admin/usage${q({ days })}`),
  usageReportAll: (days: number) => request<G.UsageReportAll>("GET", `/admin/usage${q({ days })}`),
  modelPrices: () => request<G.ModelPriceOut[]>("GET", "/admin/model-prices"),
  setPrice: (b: G.ModelPriceIn) => request<G.ModelPriceOut>("PUT", "/admin/model-prices", b),
  deletePrice: (id: string) => request<void>("DELETE", `/admin/model-prices/${e(id)}`),
  creationCodes: () => request<G.CreationCodeOut[]>("GET", "/admin/creation-codes"),
  createCode: (b: G.CreationCodeCreate) => request<G.CreationCodeCreated>("POST", "/admin/creation-codes", b),
  revokeCode: (id: string) => request<G.CreationCodeOut>("POST", `/admin/creation-codes/${e(id)}/revoke`),
  joinTokens: (ws: string) => request<G.JoinTokenOut[]>("GET", `${w(ws)}/join-tokens`),
  createToken: (ws: string, b: G.JoinTokenCreate) => request<G.JoinTokenCreated>("POST", `${w(ws)}/join-tokens`, b),
  revokeToken: (ws: string, id: string) => request<G.JoinTokenOut>("POST", `${w(ws)}/join-tokens/${e(id)}/revoke`),
};
