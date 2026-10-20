import { request, w } from "../api";
import type { SignupIn } from "../api.gen";

export interface AuthUser { id: string; email: string; display_name: string; is_admin: boolean; workspace_credits?: number }
export interface AuthMembership {
  workspace_slug: string; workspace_name: string; role: "admin" | "rep"; see_all: boolean;
  delete_own: boolean; app_user_id: string | null; app_user_name: string | null;
}
export interface Me { user: AuthUser; memberships: AuthMembership[] }
export interface DemoLogin { email: string; display_name: string }
export type AuthStatus = import("../api.gen").AuthStatus;
export interface Member {
  user_id: string; email: string; display_name: string; is_admin: boolean; disabled: boolean;
  has_password: boolean; role: "admin" | "rep"; see_all: boolean; delete_own: boolean;
  app_user_id: string | null; app_user_name: string | null; last_login_at: string | null;
}
export interface MemberCreate {
  email: string; display_name?: string; password?: string; role?: "admin" | "rep";
  see_all?: boolean; delete_own?: boolean; app_user_id?: string | null;
}
export interface MemberUpdate {
  role?: "admin" | "rep"; see_all?: boolean; delete_own?: boolean; app_user_id?: string | null;
  clear_app_user?: boolean;
}

export const authApi = {
  status: () => request<AuthStatus>("GET", "/auth/status"),
  me: () => request<Me>("GET", "/auth/me"),
  login: (email: string, password: string) => request<Me>("POST", "/auth/login", { email, password }),
  setup: (b: { email: string; display_name: string; password: string }) => request<Me>("POST", "/auth/setup", b),
  forgot: (email: string) => request<{ accepted: boolean }>("POST", "/auth/forgot", { email }),
  reset: (token: string, password: string) => request<Me>("POST", "/auth/reset", { token, password }),
  signup: (b: SignupIn) => request<Me>("POST", "/auth/signup", b),
  join: (token: string) => request<Me>("POST", "/auth/join", { token }),
  logout: () => request<void>("POST", "/auth/logout"),
  members: (ws: string) => request<Member[]>("GET", `${w(ws)}/members`),
  addMember: (ws: string, b: MemberCreate) => request<Member>("POST", `${w(ws)}/members`, b),
  updateMember: (ws: string, id: string, b: MemberUpdate) =>
    request<Member>("PATCH", `${w(ws)}/members/${encodeURIComponent(id)}`, b),
  resetPassword: (ws: string, id: string, password: string) =>
    request<void>("POST", `${w(ws)}/members/${encodeURIComponent(id)}/password`, { password }),
  disable: (ws: string, id: string) => request<void>("POST", `${w(ws)}/members/${encodeURIComponent(id)}/disable`),
  enable: (ws: string, id: string) => request<void>("POST", `${w(ws)}/members/${encodeURIComponent(id)}/enable`),
  remove: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/members/${encodeURIComponent(id)}`),
};
