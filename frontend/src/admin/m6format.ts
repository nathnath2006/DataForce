import type { EditableLimit as Limit, UsageDayUser } from "../api.gen";

/** Estimated cost in euros; `null` means no price is set for the model. */
export function formatEur(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "set a price";
  if (v === 0) return "€0.00";
  if (Math.abs(v) < 0.01) return `€${v.toFixed(4)}`;
  return `€${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatTokens(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k`;
  return String(Math.round(n));
}

export type DayMetric = "cost" | "tokens";
export interface DaySeries { days: string[]; series: { name: string; data: number[] }[] }

/** Pivot per-day-per-person rows into one stacked series per person. */
export function dayUserSeries(rows: UsageDayUser[], metric: DayMetric): DaySeries {
  const days = [...new Set(rows.map((r) => r.day))].sort();
  const names = new Map<string, Map<string, number>>();
  for (const r of rows) {
    const who = r.name || "System";
    const v = metric === "cost" ? (r.cost_eur ?? 0) : r.input_tokens + r.output_tokens;
    const m = names.get(who) ?? new Map<string, number>();
    m.set(r.day, (m.get(r.day) ?? 0) + v);
    names.set(who, m);
  }
  return { days, series: [...names].map(([name, m]) => ({ name, data: days.map((d) => m.get(d) ?? 0) })) };
}

/** A short note when some calls had no price, so a cost total is only partial. */
export function partialNote(unpriced: number): string | null {
  return unpriced > 0 ? `partial: ${unpriced} call${unpriced === 1 ? "" : "s"} without a price` : null;
}

/** Group limits for the form, keeping the server's order inside each group. */
export function groupLimits(limits: Limit[]): [string, Limit[]][] {
  const out = new Map<string, Limit[]>();
  for (const l of limits) out.set(l.group || "Other", [...(out.get(l.group || "Other") ?? []), l]);
  return [...out];
}

/** Why a typed limit cannot be saved, or null when it can. */
export function limitProblem(l: Limit, text: string): string | null {
  const v = Number(text);
  if (text.trim() === "" || !Number.isFinite(v)) return "Enter a number.";
  if (l.min != null && v < l.min) return `At least ${l.min}.`;
  if (l.max != null && v > l.max) return `At most ${l.max}.`;
  return null;
}
