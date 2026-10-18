import { e, request, w } from "../api";
import type { ProposalOut } from "./model";

export interface AiPassResult { used: boolean; calls: number; capped: number; failed: number; dropped: number }
export interface ProposeResult { run_id: string; created: number; by_kind: Record<string, number>; ambiguous: number; ai: AiPassResult | null }

export const orgApi = {
  proposals: (ws: string, accountId: string, status?: string) =>
    request<ProposalOut[]>("GET", `${w(ws)}/accounts/${e(accountId)}/org-proposals${status ? `?status=${e(status)}` : ""}`),
  propose: (ws: string, accountId: string, useAi = false) =>
    request<ProposeResult>("POST", `${w(ws)}/orgchart/propose`, { account_id: accountId, origins: ["rule", "meeting"], use_ai: useAi }),
  accept: (ws: string, id: string, managerId?: string) =>
    request<ProposalOut>("POST", `${w(ws)}/org-proposals/${e(id)}/accept`, managerId ? { manager_id: managerId } : {}),
  reject: (ws: string, id: string) => request<ProposalOut>("POST", `${w(ws)}/org-proposals/${e(id)}/reject`, {}),
};
