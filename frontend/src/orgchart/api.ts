import { e, request, w } from "../api";
import type { ProposalOut } from "./model";

export interface ProposeResult { run_id: string; created: number; by_kind: Record<string, number>; ambiguous: number }

export const orgApi = {
  proposals: (ws: string, accountId: string, status?: string) =>
    request<ProposalOut[]>("GET", `${w(ws)}/accounts/${e(accountId)}/org-proposals${status ? `?status=${e(status)}` : ""}`),
  propose: (ws: string, accountId: string) =>
    request<ProposeResult>("POST", `${w(ws)}/orgchart/propose`, { account_id: accountId, origins: ["rule", "meeting"] }),
  accept: (ws: string, id: string, managerId?: string) =>
    request<ProposalOut>("POST", `${w(ws)}/org-proposals/${e(id)}/accept`, managerId ? { manager_id: managerId } : {}),
  reject: (ws: string, id: string) => request<ProposalOut>("POST", `${w(ws)}/org-proposals/${e(id)}/reject`, {}),
};
