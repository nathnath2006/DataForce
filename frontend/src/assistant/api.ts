import { request, w } from "../api";
import type * as T from "../types";

export const aiApi = {
  get: (ws: string) => request<T.AiSettingsOut>("GET", `${w(ws)}/ai`),
  put: (ws: string, b: T.AiSettingsIn) => request<T.AiSettingsOut>("PUT", `${w(ws)}/ai`, b),
  remove: (ws: string) => request<void>("DELETE", `${w(ws)}/ai`),
  test: (ws: string) => request<T.AiSettingsOut>("POST", `${w(ws)}/ai/test`),
  ask: (ws: string, b: { scope: T.AskScope; question: string; history: T.AskTurn[] }) =>
    request<T.AskOut>("POST", `${w(ws)}/assistant/ask`, b),
};
