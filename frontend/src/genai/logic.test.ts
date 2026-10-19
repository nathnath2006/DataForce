import { describe, expect, it } from "vitest";
import { capLeft, consentText, droppedText } from "./logic";

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

describe("droppedText", () => {
  it("says why sentences were dropped", () => {
    expect(droppedText(0)).toBe("No sentence dropped.");
    expect(droppedText(9, { number_not_in_source: 7, no_citation: 2 })).toBe(
      "9 sentences dropped: 7 stated a number or date that is not in the items it cites, 2 cited no item.",
    );
  });
});
