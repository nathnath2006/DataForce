import { e, request, w } from "../api";
import type {
  ExplainMeasure, ExplainResponse, FieldsResponse, Filter, QueryRequest, QueryResponse, Source, WorkbookOut,
  WorkbookSpec, WorkbookSummary,
} from "./types";

export const wbApi = {
  list: (ws: string) => request<WorkbookSummary[]>("GET", `${w(ws)}/workbooks`),
  get: (ws: string, id: string) => request<WorkbookOut>("GET", `${w(ws)}/workbooks/${e(id)}`),
  create: (ws: string, b: { name: string; spec?: WorkbookSpec }) => request<WorkbookOut>("POST", `${w(ws)}/workbooks`, b),
  update: (ws: string, id: string, b: { name?: string; spec?: WorkbookSpec }) =>
    request<WorkbookOut>("PATCH", `${w(ws)}/workbooks/${e(id)}`, b),
  duplicate: (ws: string, id: string) => request<WorkbookOut>("POST", `${w(ws)}/workbooks/${e(id)}/duplicate`, {}),
  remove: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/workbooks/${e(id)}`),
  fields: (ws: string, source: Source) => request<FieldsResponse>("POST", `${w(ws)}/viz/fields`, { source }),
  query: (ws: string, b: QueryRequest) => request<QueryResponse>("POST", `${w(ws)}/viz/query`, b),
  explain: (ws: string, b: { source: Source; measure: ExplainMeasure; attributes: string[]; filters: Filter[] }) =>
    request<ExplainResponse>("POST", `${w(ws)}/viz/explain`, b),
};
