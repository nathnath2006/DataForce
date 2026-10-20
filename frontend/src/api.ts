import { ApiError, parseApiError } from "./lib";
import type * as T from "./types";
import { invalidate } from "./data/cache";

const BASE = "/api";

/** JSON request to the local API (shared by every feature module). */
export async function request<R>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<R> {
  const mutating = method !== "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (mutating) {
    headers["X-DataForce"] = "1";
    headers["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method, headers, credentials: "same-origin", signal,
      body: body === undefined ? (mutating ? "{}" : undefined) : JSON.stringify(body),
    });
  } catch {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    throw new ApiError(0, "network_error", "Cannot reach the DataForce API. Is `dataforce ui` running?");
  }
  if (res.status === 204) return undefined as R;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (res.status === 401 && !path.startsWith("/auth/") && !/^\/(login|setup)$/.test(window.location.pathname)) {
    window.location.assign("/login"); // the session ended: sign in again
  }
  if (!res.ok) throw parseApiError(res.status, data);
  if (mutating) {
    // A write may change any list of its workspace: drop the cached responses (/w/<slug>/...).
    const m = /^\/w\/[^/]+\//.exec(path);
    if (m) invalidate(m[0]);
  }
  return data as R;
}

export const q = (params: Record<string, string | number | undefined | null>): string => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
};
export const e = encodeURIComponent;
export const w = (ws: string) => `/w/${e(ws)}`;

export interface ListOpts { limit?: number; offset?: number; sort?: string; dir?: "asc" | "desc" }
const MAX_LIMIT = 200; // the server's cap per request

/** GET a page; a `limit` above the server cap is served by walking the pages (never truncated). */
async function getPage<I>(path: string, params: object, signal?: AbortSignal): Promise<T.Page<I>> {
  const p = params as Record<string, string | number | undefined | null>;
  const want = typeof p.limit === "number" ? p.limit : undefined;
  if (want === undefined || want <= MAX_LIMIT) return request<T.Page<I>>("GET", path + q(p), undefined, signal);
  const first = await request<T.Page<I>>("GET", path + q({ ...p, limit: MAX_LIMIT }), undefined, signal);
  const items = [...first.items];
  while (items.length < Math.min(want, first.total) && !signal?.aborted) {
    const next = await request<T.Page<I>>("GET", path + q({ ...p, limit: MAX_LIMIT, offset: items.length }), undefined, signal);
    if (next.items.length === 0) break;
    items.push(...next.items);
  }
  return { ...first, items: items.slice(0, want), limit: want };
}

export const api = {
  // workspaces and users
  listWorkspaces: () => request<T.WorkspaceOut[]>("GET", "/workspaces"),
  createWorkspace: (b: { slug: string; name: string }) => request<T.WorkspaceOut>("POST", "/workspaces", b),
  listUsers: (ws: string) => request<T.UserOut[]>("GET", `${w(ws)}/users`),
  createUser: (ws: string, b: { display_name: string; email?: string | null; role?: T.UserRole }) =>
    request<T.UserOut>("POST", `${w(ws)}/users`, b),

  // accounts
  listAccounts: (ws: string, p: { q?: string; segment?: string } & ListOpts = {}, signal?: AbortSignal) =>
    getPage<T.AccountOut>(`${w(ws)}/accounts`, p, signal),
  createAccount: (ws: string, b: T.AccountCreate) => request<T.AccountOut>("POST", `${w(ws)}/accounts`, b),
  getAccount: (ws: string, id: string) => request<T.AccountOut>("GET", `${w(ws)}/accounts/${e(id)}`),
  updateAccount: (ws: string, id: string, b: T.AccountUpdate) =>
    request<T.AccountOut>("PATCH", `${w(ws)}/accounts/${e(id)}`, b),
  deleteAccount: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/accounts/${e(id)}`),
  getOrgChart: (ws: string, id: string) => request<T.OrgChartOut>("GET", `${w(ws)}/accounts/${e(id)}/org-chart`),

  // contacts
  listContacts: (ws: string, p: { account_id?: string; q?: string } & ListOpts = {}, signal?: AbortSignal) =>
    getPage<T.ContactOut>(`${w(ws)}/contacts`, p, signal),
  createContact: (ws: string, b: T.ContactCreate) => request<T.ContactOut>("POST", `${w(ws)}/contacts`, b),
  getContact: (ws: string, id: string) => request<T.ContactOut>("GET", `${w(ws)}/contacts/${e(id)}`),
  updateContact: (ws: string, id: string, b: T.ContactUpdate) =>
    request<T.ContactOut>("PATCH", `${w(ws)}/contacts/${e(id)}`, b),
  setReportsTo: (ws: string, id: string, manager_id: string | null) =>
    request<T.ContactOut>("PUT", `${w(ws)}/contacts/${e(id)}/reports-to`, { manager_id }),
  deleteContact: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/contacts/${e(id)}`),

  // deals
  listDeals: (
    ws: string,
    p: { account_id?: string; stage?: string; lead_source?: string; owner_id?: string; q?: string } & ListOpts = {},
    signal?: AbortSignal,
  ) => getPage<T.DealOut>(`${w(ws)}/deals`, p, signal),
  createDeal: (ws: string, b: T.DealCreate) => request<T.DealOut>("POST", `${w(ws)}/deals`, b),
  getDeal: (ws: string, id: string) => request<T.DealOut>("GET", `${w(ws)}/deals/${e(id)}`),
  updateDeal: (ws: string, id: string, b: T.DealUpdate) =>
    request<T.DealOut>("PATCH", `${w(ws)}/deals/${e(id)}`, b),
  setStage: (ws: string, id: string, b: { stage: T.DealStage; closed_on?: string | null }) =>
    request<T.DealOut>("PUT", `${w(ws)}/deals/${e(id)}/stage`, b),
  deleteDeal: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/deals/${e(id)}`),

  // notes (contacts) and comments (accounts)
  listNotes: (ws: string, contactId: string) =>
    request<T.NoteOut[]>("GET", `${w(ws)}/contacts/${e(contactId)}/notes`),
  addNote: (ws: string, contactId: string, b: { body: string }) =>
    request<T.NoteOut>("POST", `${w(ws)}/contacts/${e(contactId)}/notes`, b),
  correctNote: (ws: string, id: string, b: { body: string }) =>
    request<T.NoteOut>("POST", `${w(ws)}/notes/${e(id)}/correct`, b),
  deleteNote: (ws: string, id: string) => request<T.NoteOut>("DELETE", `${w(ws)}/notes/${e(id)}`),
  noteHistory: (ws: string, id: string) => request<T.NoteOut[]>("GET", `${w(ws)}/notes/${e(id)}/history`),
  listComments: (ws: string, accountId: string) =>
    request<T.NoteOut[]>("GET", `${w(ws)}/accounts/${e(accountId)}/comments`),
  addComment: (ws: string, accountId: string, b: { body: string }) =>
    request<T.NoteOut>("POST", `${w(ws)}/accounts/${e(accountId)}/comments`, b),
  correctComment: (ws: string, id: string, b: { body: string }) =>
    request<T.NoteOut>("POST", `${w(ws)}/comments/${e(id)}/correct`, b),
  deleteComment: (ws: string, id: string) => request<T.NoteOut>("DELETE", `${w(ws)}/comments/${e(id)}`),
  commentHistory: (ws: string, id: string) => request<T.NoteOut[]>("GET", `${w(ws)}/comments/${e(id)}/history`),

  // stats
  pipeline: (ws: string) => request<T.PipelineOut>("GET", `${w(ws)}/stats/pipeline`),
  runScan: (ws: string) => request<T.ScanOut>("POST", `${w(ws)}/stats/scan`),
  latestScan: (ws: string) => request<T.ScanOut>("GET", `${w(ws)}/stats/scan/latest`),

  // connectors
  getConnector: (ws: string) => request<T.ConnectorOut>("GET", `${w(ws)}/connectors/tamtam`),
  connectTamtam: (ws: string) => request<T.ConnectStart>("POST", `${w(ws)}/connectors/tamtam/connect`),
  checkTamtam: (ws: string) => request<T.ConnectorOut>("POST", `${w(ws)}/connectors/tamtam/check`),
  disconnectTamtam: (ws: string) => request<void>("DELETE", `${w(ws)}/connectors/tamtam`),

  // enrichment
  enrich: (ws: string, contactId: string, b: T.EnrichRequest) =>
    request<T.EnrichResponse>("POST", `${w(ws)}/contacts/${e(contactId)}/enrich`, b),
  listChannels: (ws: string, contactId: string) =>
    request<T.ChannelOut[]>("GET", `${w(ws)}/contacts/${e(contactId)}/channels`),
  deleteChannel: (ws: string, contactId: string, channelId: string) =>
    request<void>("DELETE", `${w(ws)}/contacts/${e(contactId)}/channels/${e(channelId)}`),
};
