import { e, q, request, w } from "../api";
import type * as T from "../types";

export const companiesApi = {
  lookup: (ws: string, text: string) => request<T.LookupOut>("GET", `${w(ws)}/lookup${q({ q: text })}`),
  list: (ws: string, p: { q?: string; limit?: number; offset?: number } = {}) =>
    request<T.Page<T.CompanyOut>>("GET", `${w(ws)}/companies${q(p)}`),
  create: (ws: string, b: T.CompanyCreate) => request<T.CompanyOut>("POST", `${w(ws)}/companies`, b),
  get: (ws: string, id: string) => request<T.Company360>("GET", `${w(ws)}/companies/${e(id)}`),
  update: (ws: string, id: string, b: T.CompanyUpdate) =>
    request<T.CompanyOut>("PATCH", `${w(ws)}/companies/${e(id)}`, b),
  remove: (ws: string, id: string) => request<void>("DELETE", `${w(ws)}/companies/${e(id)}`),
  setAccountCompany: (ws: string, accountId: string, companyId: string | null) =>
    request<T.AccountOut>("PUT", `${w(ws)}/accounts/${e(accountId)}/company`, { company_id: companyId }),
  registrySearch: (ws: string, text: string) =>
    request<T.RegistryCompanyOut[]>("POST", `${w(ws)}/registry/search`, { q: text }),
  fromRegistry: (ws: string, siren: string, createAccount: boolean) =>
    request<T.CompanyOut>("POST", `${w(ws)}/companies/from-registry`, { siren, create_account: createAccount }),
  refresh: (ws: string, id: string) =>
    request<T.CompanyOut>("POST", `${w(ws)}/companies/${e(id)}/refresh-registry`),
};
