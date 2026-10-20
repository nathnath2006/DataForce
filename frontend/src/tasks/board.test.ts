import { describe, expect, it } from "vitest";
import type { TaskOut } from "../activity/types";
import { computeStats, dueTone, groupByColumn, moveTarget, withStatus } from "./board";

const mk = (o: Partial<TaskOut>): TaskOut => ({
  id: "1", deal_id: null, account_id: null, title: "t", due_on: null, status: "open", owner_id: null, owner_name: "Ann",
  source: "manual", evidence: {}, done_at: null, created_at: "", ...o,
});
const now = new Date(2026, 9, 21); // Wed 21 Oct 2026

describe("board", () => {
  it("groups by column and skips dismissed", () => {
    const g = groupByColumn([mk({ id: "a", status: "suggested" }), mk({ id: "b", status: "in_progress" }), mk({ id: "c", status: "dismissed" })]);
    expect(g.suggested).toHaveLength(1); expect(g.in_progress).toHaveLength(1); expect(g.open).toHaveLength(0);
  });
  it("moves one column and stops at the ends", () => {
    expect(moveTarget("open", 1)).toBe("in_progress");
    expect(moveTarget("open", -1)).toBe("suggested");
    expect(moveTarget("suggested", -1)).toBeNull();
    expect(moveTarget("done", 1)).toBeNull();
    expect(moveTarget("dismissed", 1)).toBeNull();
  });
  it("due tone", () => {
    expect(dueTone("2026-10-20", "open", now)).toBe("overdue");
    expect(dueTone("2026-10-21", "open", now)).toBe("today");
    expect(dueTone("2026-10-22", "open", now)).toBe("normal");
    expect(dueTone("2026-10-01", "done", now)).toBe("normal");
    expect(dueTone(null, "open", now)).toBe("none");
  });
  it("stats", () => {
    const s = computeStats([
      mk({ id: "1", due_on: "2026-10-19" }), mk({ id: "2", status: "in_progress", due_on: "2026-10-23" }),
      mk({ id: "3", status: "done", done_at: new Date(2026, 9, 20, 9).toISOString() }),
      mk({ id: "4", status: "done", done_at: new Date(2026, 9, 10, 9).toISOString() }),
      mk({ id: "5", status: "suggested" }), mk({ id: "6", owner_name: "Bo" }),
    ], now);
    expect(s).toMatchObject({ open: 3, overdue: 1, dueThisWeek: 2, doneThisWeek: 1 });
    expect(s.byPerson.at(0)).toEqual({ name: "Ann", open: 2 });
  });
  it("optimistic status", () => {
    expect(withStatus([mk({})], "1", "done")[0]?.status).toBe("done");
  });
});
