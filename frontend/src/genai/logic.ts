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

/** The footer under a summary: model, flagged numbers, not saved. */
export function summaryNote(s: { provider: string; model: string; flagged?: number; dropped: number }): string {
  const f = s.flagged ?? 0;
  const flagged = f === 0
    ? "Every number and date was found in the items sent."
    : `${f} sentence${f === 1 ? " has" : "s have"} a number or date not found in the items sent (marked unchecked).`;
  const cut = s.dropped > 0 ? ` ${s.dropped} sentence${s.dropped === 1 ? "" : "s"} cut for length.` : "";
  return `${s.provider} ${s.model}. ${flagged}${cut} Not saved.`;
}
