import type { TaskOut, TaskStatus } from "../activity/types";

export const COLUMNS = [
  { status: "suggested", title: "Suggested" },
  { status: "open", title: "To do" },
  { status: "in_progress", title: "In progress" },
  { status: "done", title: "Done" },
] as const satisfies readonly { status: TaskStatus; title: string }[];
export type ColumnStatus = (typeof COLUMNS)[number]["status"];
const ORDER: TaskStatus[] = COLUMNS.map((c) => c.status);

/** Group tasks by column; dismissed tasks only appear when asked for (as a fifth list). */
export function groupByColumn(tasks: TaskOut[]): Record<ColumnStatus, TaskOut[]> {
  const g: Record<ColumnStatus, TaskOut[]> = { suggested: [], open: [], in_progress: [], done: [] };
  for (const t of tasks) if (t.status in g) g[t.status as ColumnStatus].push(t);
  return g;
}

/** Status one column to the left/right, or null at the ends (or for dismissed). */
export function moveTarget(s: TaskStatus, dir: -1 | 1): ColumnStatus | null {
  const i = ORDER.indexOf(s);
  if (i < 0) return null;
  return (ORDER[i + dir] as ColumnStatus | undefined) ?? null;
}

export type DueTone = "overdue" | "today" | "normal" | "none";
const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Tone of a due date; done and dismissed tasks are never overdue. */
export function dueTone(due: string | null, status: TaskStatus, now = new Date()): DueTone {
  if (!due) return "none";
  if (status === "done" || status === "dismissed") return "normal";
  const today = ymd(now);
  return due < today ? "overdue" : due === today ? "today" : "normal";
}

export interface BoardStats { open: number; overdue: number; dueThisWeek: number; doneThisWeek: number; byPerson: { name: string; open: number }[] }

/** Monday-start week bounds of `now`, as YYYY-MM-DD (end inclusive). */
export function weekBounds(now = new Date()): { start: string; end: string } {
  const s = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
  const e = new Date(s.getFullYear(), s.getMonth(), s.getDate() + 6);
  return { start: ymd(s), end: ymd(e) };
}

/** "Open" means not done / dismissed / suggested: to do plus in progress. */
export function computeStats(tasks: TaskOut[], now = new Date()): BoardStats {
  const { start, end } = weekBounds(now);
  const today = ymd(now);
  const per = new Map<string, number>();
  let open = 0, overdue = 0, dueThisWeek = 0, doneThisWeek = 0;
  for (const t of tasks) {
    if (t.status === "open" || t.status === "in_progress") {
      open++;
      if (t.due_on && t.due_on < today) overdue++;
      if (t.due_on && t.due_on >= start && t.due_on <= end) dueThisWeek++;
      const n = t.owner_name ?? "Unassigned";
      per.set(n, (per.get(n) ?? 0) + 1);
    } else if (t.status === "done" && t.done_at) {
      const d = ymd(new Date(t.done_at));
      if (d >= start && d <= end) doneThisWeek++;
    }
  }
  const byPerson = [...per].map(([name, o]) => ({ name, open: o })).sort((a, b) => b.open - a.open || a.name.localeCompare(b.name)).slice(0, 4);
  return { open, overdue, dueThisWeek, doneThisWeek, byPerson };
}

export function initial(name: string | null): string {
  return (name?.trim()[0] ?? "?").toUpperCase();
}

/** Replace one task's status in a list (optimistic move). */
export function withStatus(tasks: TaskOut[], id: string, status: TaskStatus): TaskOut[] {
  return tasks.map((t) => (t.id === id ? { ...t, status } : t));
}
