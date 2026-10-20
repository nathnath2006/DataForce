import { describe, expect, it } from "vitest";
import { byDay, isoDay, monthGrid, splitByToday } from "./all";
import type { DocumentOut } from "./types";

const doc = (id: string, meeting_date: string | null) => ({ id, meeting_date } as DocumentOut);

describe("calendar helpers", () => {
  it("starts the grid on the Monday before the 1st", () => {
    const g = monthGrid(2026, 9); // October 2026: the 1st is a Thursday
    expect(g).toHaveLength(42);
    expect(isoDay(g[0]!)).toBe("2026-09-28");
    expect(isoDay(g[3]!)).toBe("2026-10-01");
  });
  it("splits upcoming and past around today", () => {
    const s = splitByToday([doc("a", "2026-10-25"), doc("b", "2026-10-01"), doc("c", "2026-10-20"), doc("d", null), doc("e", "2026-09-01")], "2026-10-20");
    expect(s.upcoming.map((d) => d.id)).toEqual(["c", "a"]);
    expect(s.past.map((d) => d.id)).toEqual(["b", "e"]);
  });
  it("groups by day", () => {
    const m = byDay([doc("a", "2026-10-25T10:00:00"), doc("b", "2026-10-25"), doc("c", null)]);
    expect(m.get("2026-10-25")?.map((d) => d.id)).toEqual(["a", "b"]);
    expect(m.size).toBe(1);
  });
});
