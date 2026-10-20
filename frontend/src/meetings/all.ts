import { meetingsApi } from "./api";
import type { DocumentOut } from "./types";

const PAGE = 200;
const MAX = 2000;

/** The newest meetings of the workspace (server-paged by 200, newest first, at most 2,000) for the calendar and the summary.
 *  The documents list has no date filter, so the window is "the newest 2,000 by meeting date". */
export async function loadAllMeetings(ws: string): Promise<{ items: DocumentOut[]; total: number }> {
  const items: DocumentOut[] = [];
  let total = 0;
  for (let offset = 0; offset < MAX; offset += PAGE) {
    const p = await meetingsApi.page(ws, { limit: PAGE, offset, sort: "meeting_date", dir: "desc" });
    total = p.total;
    items.push(...p.items);
    if (items.length >= total || p.items.length === 0) break;
  }
  return { items, total };
}

/** YYYY-MM-DD of a local date. */
export function isoDay(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/** Meetings on or after `today` (soonest first), and the latest ones before it (newest first). */
export function splitByToday(docs: DocumentOut[], today: string): { upcoming: DocumentOut[]; past: DocumentOut[] } {
  const dated = docs.filter((d) => d.meeting_date);
  const day = (d: DocumentOut) => (d.meeting_date ?? "").slice(0, 10);
  return {
    upcoming: dated.filter((d) => day(d) >= today).sort((a, b) => day(a).localeCompare(day(b))),
    past: dated.filter((d) => day(d) < today).sort((a, b) => day(b).localeCompare(day(a))),
  };
}

/** The 6x7 grid of days shown for a month (weeks start on Monday). */
export function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const lead = (first.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - lead + i));
}

/** Meetings grouped by YYYY-MM-DD. */
export function byDay(docs: DocumentOut[]): Map<string, DocumentOut[]> {
  const m = new Map<string, DocumentOut[]>();
  for (const d of docs) {
    if (!d.meeting_date) continue;
    const k = d.meeting_date.slice(0, 10);
    const l = m.get(k) ?? [];
    l.push(d);
    m.set(k, l);
  }
  return m;
}
