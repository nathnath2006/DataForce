import { e, q, request, w } from "../api";
import type * as T from "../types";
import type * as A from "./types";

export const activityApi = {
  createActivity: (ws: string, accountId: string, b: A.ActivityCreate) =>
    request<A.ActivityOut>("POST", `${w(ws)}/accounts/${e(accountId)}/activities`, b),
  deleteActivity: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/activities/${e(id)}`),
  listTasks: (ws: string, p: { deal_id?: string; account_id?: string }) =>
    request<A.TaskOut[]>("GET", `${w(ws)}/tasks${q(p)}`),
  createTask: (ws: string, b: A.TaskCreate) => request<A.TaskOut>("POST", `${w(ws)}/tasks`, b),
  updateTask: (ws: string, id: string, b: A.TaskUpdate) => request<A.TaskOut>("PATCH", `${w(ws)}/tasks/${e(id)}`, b),
  acceptTask: (ws: string, id: string) => request<A.TaskOut>("POST", `${w(ws)}/tasks/${e(id)}/accept`),
  deleteTask: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/tasks/${e(id)}`),
  moveStage: (ws: string, dealId: string, b: A.MoveStage) =>
    request<T.DealOut>("POST", `${w(ws)}/deals/${e(dealId)}/move`, b),
  timeline: (ws: string, scope: "deals" | "accounts", id: string, p: { limit?: number; before?: string | null; kinds?: string }) =>
    request<A.TimelinePage>("GET", `${w(ws)}/${scope}/${e(id)}/timeline${q(p)}`),
};
