import { describe, expect, it } from "vitest";
import { askNotice } from "./AskPanel";

describe("askNotice", () => {
  it("names the company, or this account, and what is sent", () => {
    expect(askNotice("Acme Group", "gemini")).toBe(
      "Your question and the CRM data of Acme Group, including all its accounts' people with their titles, deals, notes, comments and meeting titles, are sent to gemini.");
    expect(askNotice("this account", "your configured AI provider")).toContain("of this account, including");
  });
});
