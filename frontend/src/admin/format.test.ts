import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, purposeLabel } from "./format";

describe("formatBytes", () => {
  it("scales units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
  it("is safe on bad input", () => { expect(formatBytes(NaN)).toBe("—"); expect(formatBytes(-1)).toBe("—"); });
});

describe("formatDuration", () => {
  it("formats ranges", () => {
    expect(formatDuration(250)).toBe("250 ms");
    expect(formatDuration(1500)).toBe("1.5 s");
    expect(formatDuration(125000)).toBe("2 min 5 s");
    expect(formatDuration(3_900_000)).toBe("1 h 5 min");
  });
  it("handles null", () => { expect(formatDuration(null)).toBe("—"); });
});

describe("purposeLabel", () => {
  it("names the recorded purposes in plain words", () => {
    expect(purposeLabel("explanation")).toBe("Org statements from meetings");
    expect(purposeLabel("title_classification")).toBe("Job titles");
    expect(purposeLabel("something_new")).toBe("something_new");
  });
});
