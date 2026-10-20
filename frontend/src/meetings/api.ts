import { e, q, request, w } from "../api";
import { ApiError, parseApiError } from "../lib";
import type * as T from "../types";
import type { DocumentDetail, DocumentOut, ThemeRunIn, ThemeRunOut } from "./types";

export interface UploadFields { file: File; title?: string; meeting_date?: string; deal_id?: string }

/** Multipart upload: the browser sets the multipart Content-Type (with its boundary). */
async function upload(ws: string, accountId: string, f: UploadFields): Promise<DocumentOut> {
  const fd = new FormData();
  fd.append("file", f.file);
  if (f.title) fd.append("title", f.title);
  if (f.meeting_date) fd.append("meeting_date", f.meeting_date);
  if (f.deal_id) fd.append("deal_id", f.deal_id);
  let res: Response;
  try {
    res = await fetch(`/api${w(ws)}/accounts/${e(accountId)}/documents`, {
      method: "POST", headers: { "X-DataForce": "1", Accept: "application/json" },
      credentials: "same-origin", body: fd,
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the DataForce API. Is `dataforce ui` running?");
  }
  let data: unknown = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) throw parseApiError(res.status, data);
  return data as DocumentOut;
}

export const meetingsApi = {
  forAccount: (ws: string, id: string) => request<DocumentOut[]>("GET", `${w(ws)}/accounts/${e(id)}/documents`),
  forCompany: (ws: string, id: string) => request<DocumentOut[]>("GET", `${w(ws)}/companies/${e(id)}/documents`),
  page: (ws: string, p: { limit: number; offset: number; sort?: string; dir?: "asc" | "desc"; q?: string }, signal?: AbortSignal) =>
    request<T.Page<DocumentOut>>("GET", `${w(ws)}/documents${q(p)}`, undefined, signal),
  get: (ws: string, id: string) => request<DocumentDetail>("GET", `${w(ws)}/documents/${e(id)}`),
  remove: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/documents/${e(id)}`),
  upload,
  runThemes: (ws: string, b: ThemeRunIn) => request<ThemeRunOut>("POST", `${w(ws)}/themes/run`, b),
  /** The latest run, or null when there is none yet (404). */
  latestThemes: async (ws: string): Promise<ThemeRunOut | null> => {
    try {
      return await request<ThemeRunOut>("GET", `${w(ws)}/themes/latest`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  },
  companyAccounts: async (ws: string, companyId: string): Promise<T.AccountOut[]> =>
    (await request<T.Company360>("GET", `${w(ws)}/companies/${e(companyId)}`)).accounts,
  accountDeals: async (ws: string, accountId: string): Promise<T.DealOut[]> =>
    (await request<T.Page<T.DealOut>>("GET", `${w(ws)}/deals${q({ account_id: accountId, limit: 200 })}`)).items,
};
