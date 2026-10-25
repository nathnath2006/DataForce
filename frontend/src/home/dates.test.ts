import { describe, expect, it } from "vitest";
import { ago, relDay } from "./dates";

const now = new Date("2026-10-25T10:00:00");

describe("relDay", () => {
  it("names today, tomorrow and late days", () => {
    expect(relDay("2026-10-25", now)).toBe("Today");
    expect(relDay("2026-10-26", now)).toBe("Tomorrow");
    expect(relDay("2026-10-24", now)).toBe("1 day late");
    expect(relDay("2026-10-20", now)).toBe("5 days late");
    expect(relDay(null, now)).toBe("No date");
  });
});

describe("ago", () => {
  it("is relative for a week, then a date", () => {
    expect(ago("2026-10-25T09:59:30", now)).toBe("just now");
    expect(ago("2026-10-25T09:15:00", now)).toBe("45 min ago");
    expect(ago("2026-10-25T07:00:00", now)).toBe("3 h ago");
    expect(ago("2026-10-24T09:00:00", now)).toBe("yesterday");
    expect(ago("2026-10-21T09:00:00", now)).toBe("4 days ago");
    expect(ago("2026-10-01T09:00:00", now)).not.toMatch(/ago/);
  });
});
