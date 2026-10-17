import { describe, expect, it } from "vitest";
import { formatAddress, formatSiren, registrySummary, sizeLabel } from "./format";
import type { RegistryCompanyOut } from "../types";

const r: RegistryCompanyOut = {
  siren: "791012081", name: "DATAIKU", address_line: null, postal_code: "75012", city: "PARIS",
  naf_code: "58.29C", legal_category: "5710", size_bracket: "32", category: "ETI", created_on: "2013-01-26",
  active: true, sole_trader: false, in_crm_company_id: null,
};

describe("registry formatting", () => {
  it("groups the SIREN", () => {
    expect(formatSiren("791012081")).toBe("791 012 081");
    expect(formatSiren("12")).toBe("12");
    expect(formatSiren(null)).toBe("—");
  });
  it("labels sizes", () => {
    expect(sizeLabel("32")).toBe("250-499 employees");
    expect(sizeLabel("NN")).toBe("—");
    expect(sizeLabel("__proto__")).toBe("—");
  });
  it("formats addresses with protected (missing) parts", () => {
    expect(formatAddress({ address_line: null, postal_code: "75012", city: "PARIS" })).toBe("75012 PARIS");
    expect(formatAddress({})).toBe("—");
  });
  it("summarises a result", () => {
    expect(registrySummary(r)).toBe("SIREN 791 012 081 · PARIS · NAF 58.29C · 250-499 employees · active");
    expect(registrySummary({ ...r, active: false, size_bracket: null })).toContain("closed");
  });
});
