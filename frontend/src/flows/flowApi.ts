import { e, request, w } from "../api";
import { ApiError, parseApiError } from "../lib";
import type {
  Catalog, ConnectionIn, ConnectionOut, FileOut, FlowGraph, FlowOut, FlowSummary, PgTable, RunResponse,
} from "./types";

/** Multipart upload: the browser sets the multipart Content-Type (with its boundary). */
async function upload(ws: string, file: File, sheet?: string): Promise<FileOut> {
  const fd = new FormData();
  fd.append("file", file);
  if (sheet) fd.append("sheet", sheet);
  let res: Response;
  try {
    res = await fetch(`/api${w(ws)}/files`, {
      method: "POST", headers: { "X-DataForce": "1", Accept: "application/json" },
      credentials: "same-origin", body: fd,
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the DataForce API. Is `dataforce ui` running?");
  }
  let data: unknown = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) throw parseApiError(res.status, data);
  return data as FileOut;
}

export const flowApi = {
  list: (ws: string) => request<FlowSummary[]>("GET", `${w(ws)}/flows`),
  get: (ws: string, id: string) => request<FlowOut>("GET", `${w(ws)}/flows/${e(id)}`),
  create: (ws: string, b: { name: string; description?: string; graph?: FlowGraph }) =>
    request<FlowOut>("POST", `${w(ws)}/flows`, b),
  update: (ws: string, id: string, b: { name?: string; description?: string; graph?: FlowGraph }) =>
    request<FlowOut>("PUT", `${w(ws)}/flows/${e(id)}`, b),
  remove: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/flows/${e(id)}`),
  run: (ws: string, graph: FlowGraph, target?: string) =>
    request<RunResponse>("POST", `${w(ws)}/flows/run`, target ? { graph, target } : { graph }),
  catalog: (ws: string) => request<Catalog>("GET", `${w(ws)}/flows/catalog`),

  files: (ws: string) => request<FileOut[]>("GET", `${w(ws)}/files`),
  upload,
  deleteFile: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/files/${e(id)}`),

  connections: (ws: string) => request<ConnectionOut[]>("GET", `${w(ws)}/connections`),
  createConnection: (ws: string, b: ConnectionIn) => request<ConnectionOut>("POST", `${w(ws)}/connections`, b),
  updateConnection: (ws: string, id: string, b: Partial<ConnectionIn>) =>
    request<ConnectionOut>("PATCH", `${w(ws)}/connections/${e(id)}`, b),
  deleteConnection: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/connections/${e(id)}`),
  testConnection: (ws: string, id: string) => request<ConnectionOut>("POST", `${w(ws)}/connections/${e(id)}/test`),
  tables: (ws: string, id: string) => request<PgTable[]>("GET", `${w(ws)}/connections/${e(id)}/tables`),
};
