import type { AiPreview } from "./api";

/** The consent sentence, built only from the preview (what would be sent, and to whom). */
export function consentText(p: AiPreview): string {
  const items = `${p.n_items} item${p.n_items === 1 ? "" : "s"}`;
  const cut = p.truncated ? " The text was cut to the size limit, newest first." : "";
  return `This sends ${items} (${p.n_chars.toLocaleString("en-GB")} characters): deal facts, stage history, notes, comments and activities, to ${p.provider} ${p.model}.${cut}`;
}

export function capLeft(p: AiPreview): number {
  return Math.max(0, p.daily_cap - p.calls_today);
}

const REASON: Record<string, string> = {
  no_citation: "cited no item",
  number_not_in_source: "stated a number or date that is not in the items it cites",
  too_long: "went past the length limit",
};

/** "9 sentences dropped: 7 stated a number…, 2 cited no item." */
export function droppedText(dropped: number, reasons: Record<string, number> = {}): string {
  if (dropped === 0) return "No sentence dropped.";
  const parts = Object.entries(reasons).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${REASON[k] ?? k}`);
  const head = `${dropped} sentence${dropped === 1 ? "" : "s"} dropped`;
  return parts.length ? `${head}: ${parts.join(", ")}.` : `${head}.`;
}
