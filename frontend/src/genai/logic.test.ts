import { describe, expect, it } from "vitest";
import { capLeft, consentText, summaryNote } from "./logic";

const p = { n_items: 2, n_chars: 1234, truncated: true, by_kind: {}, provider: "gemini", model: "m", calls_today: 3, daily_cap: 5 };

describe("genai logic", () => {
  it("builds the consent sentence from the preview", () => {
    const t = consentText(p);
    expect(t).toContain("2 items");
    expect(t).toContain("gemini m");
    expect(t).toContain("cut");
  });
  it("counts the calls left", () => {
    expect(capLeft(p)).toBe(2);
    expect(capLeft({ ...p, calls_today: 9 })).toBe(0);
  });
});

describe("summaryNote", () => {
  it("says what was flagged", () => {
    const base = { provider: "gemini", model: "m", dropped: 0 };
    expect(summaryNote({ ...base, flagged: 0 })).toBe("gemini m. Every number and date was found in the items sent. Not saved.");
    expect(summaryNote({ ...base, flagged: 2, dropped: 1 })).toBe(
      "gemini m. 2 sentences have a number or date not found in the items sent (marked unchecked). 1 sentence cut for length. Not saved.",
    );
  });
});
