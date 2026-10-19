import type { AiPreview } from "./api";

/** The consent sentence, built only from the preview (what would be sent, and to whom). */
export function consentText(p: AiPreview): string {
  const items = `${p.n_items} item${p.n_items === 1 ? "" : "s"}`;
  const cut = p.truncated ? " The text was cut to the size limit, newest first." : "";
  return `This sends ${items} (${p.n_chars.toLocaleString("en-GB")} characters) of notes, comments and activities to ${p.provider} ${p.model}.${cut}`;
}

export function capLeft(p: AiPreview): number {
  return Math.max(0, p.daily_cap - p.calls_today);
}
