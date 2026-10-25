import { formatDateTime } from "../lib";

/** Relative dates for the Home cards. */
function dayDiff(iso: string, now: Date): number {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  const t = new Date(now); t.setHours(12, 0, 0, 0);
  return Math.round((d.getTime() - t.getTime()) / 86_400_000);
}

/** "Today", "Tomorrow", "3 days late", "Fri 24 Oct". */
export function relDay(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "No date";
  const diff = dayDiff(iso, now);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff < 0) return diff === -1 ? "1 day late" : `${-diff} days late`;
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

/** "5 min ago", "3 h ago", "2 days ago", then the date. */
export function ago(iso: string, now: Date = new Date()): string {
  const s = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(s)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86_400) { const d = Math.floor(s / 86_400); return d === 1 ? "yesterday" : `${d} days ago`; }
  return formatDateTime(iso);
}
