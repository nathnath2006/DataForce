import type { RegistryCompanyOut } from "../types";

const SIZES = new Map([
  ["00", "0 employees"], ["01", "1-2 employees"], ["02", "3-5 employees"], ["03", "6-9 employees"],
  ["11", "10-19 employees"], ["12", "20-49 employees"], ["21", "50-99 employees"],
  ["22", "100-199 employees"], ["31", "200-249 employees"], ["32", "250-499 employees"],
  ["41", "500-999 employees"], ["42", "1,000-1,999 employees"], ["51", "2,000-4,999 employees"],
  ["52", "5,000-9,999 employees"], ["53", "10,000+ employees"],
]);

/** Registry size bracket code to words; unknown or missing codes give an em dash. */
export function sizeLabel(code: string | null | undefined): string {
  return (code && SIZES.get(code)) || "—";
}

/** "123 456 789" (groups of three) for display; anything that is not 9 digits is returned as is. */
export function formatSiren(s: string | null | undefined): string {
  if (!s) return "—";
  return /^\d{9}$/.test(s) ? `${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6)}` : s;
}

export function formatAddress(c: { address_line?: string | null; postal_code?: string | null; city?: string | null }): string {
  const town = [c.postal_code, c.city].filter(Boolean).join(" ");
  const parts = [c.address_line, town].filter((x): x is string => !!x);
  return parts.length ? parts.join(", ") : "—";
}

/** One-line summary of a registry result, as plain text. */
export function registrySummary(r: RegistryCompanyOut): string {
  const bits = [
    `SIREN ${formatSiren(r.siren)}`,
    r.city ?? null,
    r.naf_code ? `NAF ${r.naf_code}` : null,
    r.size_bracket ? sizeLabel(r.size_bracket) : null,
    r.active ? "active" : "closed",
  ];
  return bits.filter((x): x is string => !!x && x !== "—").join(" · ");
}
