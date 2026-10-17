import type { ErrorCode, OrgChartNode, StatValue } from "./types";

// ---- API errors ----
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | "http_error" | "network_error";
  constructor(status: number, code: ApiError["code"], message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Parse `{"error": {"code", "message"}}`; anything else becomes a generic http_error. */
export function parseApiError(status: number, body: unknown): ApiError {
  if (typeof body === "object" && body !== null && "error" in body) {
    const e = (body as { error: unknown }).error;
    if (typeof e === "object" && e !== null) {
      const { code, message } = e as { code?: unknown; message?: unknown };
      if (typeof code === "string" && typeof message === "string") {
        return new ApiError(status, code as ErrorCode, message);
      }
    }
  }
  return new ApiError(status, "http_error", `Request failed (HTTP ${status})`);
}

// ---- authorize_url check ----
/** True only for an https URL whose origin equals the issuer's origin. */
export function isSafeAuthorizeUrl(authorizeUrl: string, issuer: string | null | undefined): boolean {
  if (!issuer) return false;
  try {
    const u = new URL(authorizeUrl);
    const i = new URL(issuer);
    return u.protocol === "https:" && i.protocol === "https:" && u.origin === i.origin;
  } catch {
    return false;
  }
}

// ---- org chart ----
export interface OrgTreeNode { node: OrgChartNode; children: OrgTreeNode[]; orphan: boolean }

/**
 * Build a forest from flat nodes. Roots: no manager. Orphans: manager id not in the list (shown as
 * roots, flagged). Cycles (should not exist): every node still appears once; a node in a cycle is
 * promoted to a root where the walk first reaches it.
 */
export function buildOrgTree(nodes: OrgChartNode[]): OrgTreeNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const kids = new Map<string, OrgChartNode[]>();
  const roots: { n: OrgChartNode; orphan: boolean }[] = [];
  for (const n of nodes) {
    const m = n.reports_to_id;
    if (m && m !== n.id && byId.has(m)) {
      const l = kids.get(m) ?? [];
      l.push(n);
      kids.set(m, l);
    } else {
      roots.push({ n, orphan: m !== null && m !== n.id && !byId.has(m) });
    }
  }
  const seen = new Set<string>();
  const sortByName = (a: OrgChartNode, b: OrgChartNode) => a.full_name.localeCompare(b.full_name);
  const build = (n: OrgChartNode, orphan: boolean): OrgTreeNode => {
    seen.add(n.id);
    const children = (kids.get(n.id) ?? [])
      .filter((c) => !seen.has(c.id))
      .sort(sortByName)
      .map((c) => build(c, false));
    return { node: n, children, orphan };
  };
  const out = roots.sort((a, b) => sortByName(a.n, b.n)).map((r) => build(r.n, r.orphan));
  // Nodes unreachable from any root belong to a cycle: surface each once.
  for (const n of [...nodes].sort(sortByName)) {
    if (!seen.has(n.id)) out.push(build(n, false));
  }
  return out;
}

// ---- formatting ----
const eur0 = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });

export function formatEur(v: number | string | null | undefined, decimals = false): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return (decimals ? eur2 : eur0).format(n);
}

/** A rate in [0,1] as a percentage: 0.4567 -> "45.7%". */
export function formatPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/** A difference of rates in [-1,1] as signed percentage points: 0.123 -> "+12.3 pts". */
export function formatPts(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const x = v * 100;
  return `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)} pts`;
}

export function formatNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-IE", { maximumFractionDigits: digits });
}

type Unit = "rate" | "days" | "eur";
export function unitOf(metric: string): Unit {
  return metric === "win_rate" ? "rate" : metric === "cycle_days" ? "days" : "eur";
}

export function formatValue(v: number | null | undefined, unit: Unit): string {
  if (unit === "rate") return formatPct(v);
  if (unit === "days") return v === null || v === undefined ? "—" : `${formatNum(v)} d`;
  return formatEur(v);
}

export function formatDiff(v: number | null | undefined, unit: Unit): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (unit === "rate") return formatPts(v);
  const s = v > 0 ? "+" : v < 0 ? "−" : "";
  const a = Math.abs(v);
  return unit === "days" ? `${s}${formatNum(a)} d` : `${s}${formatEur(a)}`;
}

/** "45.7% (95% CI 38.2% to 53.4%)". Never shows a number without its interval when it has one. */
export function formatWithCi(
  value: number | null, low: number | null, high: number | null, unit: Unit, confidence = 0.95,
): string {
  const base = formatValue(value, unit);
  if (low === null || high === null) return base;
  return `${base} (${Math.round(confidence * 100)}% CI ${formatValue(low, unit)} to ${formatValue(high, unit)})`;
}

export function formatStat(s: StatValue, confidence = 0.95): string {
  return formatWithCi(s.value, s.ci_low, s.ci_high, unitOf(s.metric), confidence);
}

export function formatDiffWithCi(
  diff: number | null, low: number | null, high: number | null, unit: Unit, confidence = 0.95,
): string {
  const base = formatDiff(diff, unit);
  if (low === null || high === null) return base;
  return `${base} (${Math.round(confidence * 100)}% CI ${formatDiff(low, unit)} to ${formatDiff(high, unit)})`;
}

export function formatQ(q: number | null | undefined): string {
  if (q === null || q === undefined || !Number.isFinite(q)) return "—";
  return q < 0.001 ? "<0.001" : q.toFixed(3);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function label(s: string | null | undefined): string {
  if (!s) return "—";
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
