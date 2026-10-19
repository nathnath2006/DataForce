import { e, q, request, w } from "../api";
import type * as M from "./types";

export const mailboxApi = {
  status: (ws: string) => request<M.MailboxStatusOut>("GET", `${w(ws)}/mailbox`),
  setClient: (ws: string, p: M.MailProvider, b: { client_id: string; client_secret?: string | null }) =>
    request<M.MailboxStatusOut>("PUT", `${w(ws)}/mailbox/${p}/client`, b),
  connect: (ws: string, p: M.MailProvider) =>
    request<{ authorize_url: string }>("POST", `${w(ws)}/mailbox/${p}/connect`),
  sync: (ws: string, provider?: M.MailProvider) =>
    request<M.MailboxSyncResultOut>("POST", `${w(ws)}/mailbox/sync`, provider ? { provider } : {}),
  disconnect: (ws: string, p: M.MailProvider) => request<void>("DELETE", `${w(ws)}/mailbox/${p}`),
  messages: (ws: string, p: { deal_id?: string; state?: M.MessageState; q?: string; unmatched?: boolean; limit?: number }) =>
    request<M.MailboxMessageOut[]>("GET", `${w(ws)}/mailbox/messages${q({ ...p, unmatched: p.unmatched ? "true" : undefined })}`),
  link: (ws: string, id: string, dealId: string) =>
    request<M.MailboxMessageOut>("POST", `${w(ws)}/mailbox/messages/${e(id)}/link`, { deal_id: dealId }),
  ignore: (ws: string, id: string) => request<M.MailboxMessageOut>("POST", `${w(ws)}/mailbox/messages/${e(id)}/ignore`),
  unlink: (ws: string, id: string) => request<M.MailboxMessageOut>("POST", `${w(ws)}/mailbox/messages/${e(id)}/unlink`),
};
