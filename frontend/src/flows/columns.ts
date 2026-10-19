import type { ColumnProfile } from "./types";

export type Meaning = "money" | "date" | "category" | "id" | "number" | "text";

const MONEY = new Set(["amount", "price", "revenue", "cost", "value", "arr", "mrr", "fee", "salary", "budget", "total", "balance", "currency"]);
const CATEGORY_MAX_UNIQUE = 20;

function words(name: string): string[] {
  return name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

/** A guess, never a fact. Rule, first match wins:
 *  1. id: the name's last word is id/uuid/key/code, or the name is "id";
 *  2. date: dtype date or datetime;
 *  3. money: a number column with a word like amount, price, revenue, cost, value, arr, mrr, fee, salary, budget, total;
 *  4. number: any other number or integer column;
 *  5. category: a boolean, or a text column with at most 20 distinct values that repeat (distinct <= half the filled rows);
 *  6. text: everything else. */
export function meaningOf(p: Pick<ColumnProfile, "name" | "dtype" | "non_null" | "n_unique">): Meaning {
  const w = words(p.name);
  if (["id", "uuid", "key", "code"].includes(w[w.length - 1] ?? "")) return "id";
  if (p.dtype === "date" || p.dtype === "datetime") return "date";
  if (p.dtype === "number" || p.dtype === "integer") return w.some((x) => MONEY.has(x)) ? "money" : "number";
  if (p.dtype === "boolean") return "category";
  if (p.dtype === "text" && p.non_null > 0 && p.n_unique <= CATEGORY_MAX_UNIQUE && p.n_unique * 2 <= p.non_null) return "category";
  return "text";
}

export interface Bar { x: number; y: number; w: number; h: number }

/** Bars for a sparkline of `values` in a width x height box, scaled to the largest value.
 *  A non-zero value always keeps at least 1px of height; all-zero or empty gives flat bars. */
export function sparkBars(values: number[], width: number, height: number, gap = 1): Bar[] {
  const n = values.length;
  if (n === 0) return [];
  const bw = Math.max(1, (width - gap * (n - 1)) / n);
  const safe = values.map((v) => (Number.isFinite(v) ? v : 0));
  const max = Math.max(...safe, 0);
  return safe.map((v, i) => {
    const h = max <= 0 || v <= 0 ? 0 : Math.max(1, (v / max) * height);
    return { x: i * (bw + gap), y: height - h, w: bw, h };
  });
}

export function pct(non_null: number, n: number): number {
  return n > 0 ? Math.round((non_null / n) * 100) : 0;
}
