import type { NodeResult } from "./types";

/** The canvas node's state edge (VISUAL-IDENTITY §4, honest state):
 *  error = bad; selected = primary; green only for a result the engine verified (a model whose
 *  status is verified, a stats block with at least one verified comparison); a stats block with
 *  none, a model not verified, clusters (always exploratory) or a skipped block = not verified;
 *  anything else is idle. Warnings show as the node's tag, not as its edge: a note such as
 *  "rows with a missing outcome were excluded" does not change what the engine verified. */
export function nodeState(res: NodeResult | undefined, selected: boolean): string {
  if (res?.status === "error") return "st-bad";
  if (selected) return "st-sel";
  if (!res) return "";
  if (res.status === "skipped") return "st-unverified";
  const v = res.view;
  if (!v) return "";
  if (v.kind === "model") return v.status === "verified" ? "st-ok" : "st-unverified";
  if (v.kind === "stats") return v.rows.some((r) => r.status === "verified") ? "st-ok" : "st-unverified";
  if (v.kind === "cluster") return "st-unverified";
  if (v.kind === "score") return v.status === "verified" ? "st-ok" : "st-unverified";
  return "";
}
