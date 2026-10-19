import { describe, expect, it } from "vitest";
import { dotClass, FILTERS, groupByDay, isFuture, kindsParam, moveDateError, toLocalInput } from "./logic";
import type { TimelineItem } from "./types";

const item = (id: string, at: string, kind: TimelineItem["kind"] = "call", refs = {}): TimelineItem => ({
  id, kind, at, title: id, title_untrusted: false, summary: null, summary_untrusted: false, author_name: null, refs,
});

describe("timeline logic", () => {
  it("groups by local day and keeps order", () => {
    const g = groupByDay([item("a", "2026-10-19T12:00:00"), item("b", "2026-10-19T09:00:00"), item("c", "2026-10-17T09:00:00")]);
    expect(g.map((x) => x.items.map((i) => i.id))).toEqual([["a", "b"], ["c"]]);
    expect(g[0]?.day).toBe("2026-10-19");
  });
  it("maps filters to kinds", () => {
    expect(kindsParam([])).toBeUndefined();
    expect(kindsParam(["note", "call"])).toBe("call,note,comment");
    expect(FILTERS.flatMap((f) => f.kinds)).toHaveLength(8);
  });
  it("colours dots by kind with tokens only", () => {
    expect(dotClass(item("s", "x", "stage"))).toBe("dot-stage");
    expect(dotClass(item("m", "x", "meeting"))).toBe("dot-meeting");
    expect(dotClass(item("c", "x", "email"))).toBe("dot-soft");
    expect(dotClass(item("t", "x", "task", { status: "done" }))).toBe("dot-ok");
    expect(dotClass(item("t", "x", "task", { status: "open" }))).toBe("dot-warn");
  });
  it("refuses future and too-early stage dates", () => {
    expect(moveDateError("2026-10-20", "2026-10-19", "2026-01-01")).toMatch(/future/);
    expect(moveDateError("2025-12-31", "2026-10-19", "2026-01-01")).toMatch(/before/);
    expect(moveDateError("2026-10-19", "2026-10-19", "2026-01-01")).toBeNull();
    expect(moveDateError("", "2026-10-19", "2026-01-01")).toBeNull();
  });
  it("detects future activity times", () => {
    const now = new Date(2026, 9, 19, 12, 0);
    expect(toLocalInput(now)).toBe("2026-10-19T12:00");
    expect(isFuture("2026-10-19T12:01", now)).toBe(true);
    expect(isFuture("2026-10-19T11:59", now)).toBe(false);
  });
});
