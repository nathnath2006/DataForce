import type { TimelineItem, TimelineKind } from "./types";

export const STAGES = ["prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost"] as const;

/** The filter chips, each covering one or more timeline kinds. */
export const FILTERS: { id: string; label: string; kinds: TimelineKind[] }[] = [
  { id: "stage", label: "Stages", kinds: ["stage"] },
  { id: "call", label: "Calls", kinds: ["call"] },
  { id: "email", label: "Emails", kinds: ["email"] },
  { id: "meeting", label: "Meetings", kinds: ["meeting"] },
  { id: "note", label: "Notes", kinds: ["note", "comment"] },
  { id: "task", label: "Tasks", kinds: ["task"] },
  { id: "other", label: "Other", kinds: ["other"] },
];

/** `kinds` query value for the selected chips; undefined (= everything) when none is selected. */
export function kindsParam(selected: string[]): string | undefined {
  if (selected.length === 0) return undefined;
  return FILTERS.filter((f) => selected.includes(f.id)).flatMap((f) => f.kinds).join(",");
}

/** Local calendar day of an ISO instant, as YYYY-MM-DD. */
export function dayKey(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Items (already newest first) grouped by day, keeping their order. */
export function groupByDay(items: TimelineItem[]): { day: string; items: TimelineItem[] }[] {
  const out: { day: string; items: TimelineItem[] }[] = [];
  for (const it of items) {
    const day = dayKey(it.at);
    const last = out[out.length - 1];
    if (last && last.day === day) last.items.push(it);
    else out.push({ day, items: [it] });
  }
  return out;
}

/** CSS modifier of the dot: tokens only (see activity.css). */
export function dotClass(it: Pick<TimelineItem, "kind" | "refs">): string {
  switch (it.kind) {
    case "stage": return "dot-stage";
    case "meeting": return "dot-meeting";
    case "task": {
      const s = it.refs?.status;
      return s === "done" ? "dot-ok" : s === "open" ? "dot-warn" : "dot-soft";
    }
    default: return "dot-soft";
  }
}

/** Why a stage-change date is refused, or null. Dates are YYYY-MM-DD. */
export function moveDateError(date: string, today: string, createdOn: string): string | null {
  if (!date) return null;
  if (date > today) return "The date cannot be in the future.";
  if (date < createdOn) return "The date is before the deal was created.";
  return null;
}

/** A datetime-local value ("2026-10-19T14:30") for an instant, in local time. */
export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function isFuture(localValue: string, now: Date = new Date()): boolean {
  const t = new Date(localValue).getTime();
  return !Number.isNaN(t) && t > now.getTime();
}
