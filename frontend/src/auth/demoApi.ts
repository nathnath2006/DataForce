import { request } from "../api";
import type { Me } from "./api";
import type { DemoAiKeyIn, DemoAiKeyOut, DemoIdentity } from "./demoTypes";

export const demoApi = {
  start: (as?: string) => request<Me>("POST", "/auth/demo", as ? { as } : {}),
  identities: () => request<DemoIdentity[]>("GET", "/auth/demo/identities"),
  getKey: () => request<DemoAiKeyOut>("GET", "/auth/demo/ai-key"),
  putKey: (b: DemoAiKeyIn) => request<DemoAiKeyOut>("PUT", "/auth/demo/ai-key", b),
  deleteKey: () => request<DemoAiKeyOut | void>("DELETE", "/auth/demo/ai-key"),
};
