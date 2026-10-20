import { describe, expect, it } from "vitest";
import { currentIdentity, demoBlocked, identityLabel, landingPath, sortIdentities } from "./demoLogic";

const ids = [
  { as: "u2", label: "Zoe Rep", role: "rep" as const },
  { as: "admin", label: "Demo admin", role: "admin" as const },
  { as: "u1", label: "Adam Rep", role: "rep" as const },
];
describe("demo logic", () => {
  it("sorts admin first then by name", () => {
    expect(sortIdentities(ids).map((i) => i.as)).toEqual(["admin", "u1", "u2"]);
  });
  it("labels reps", () => {
    expect(identityLabel(ids[1]!)).toBe("Demo admin");
    expect(identityLabel(ids[0]!)).toBe("Zoe Rep (rep)");
  });
  it("blocks only in a demo session", () => {
    expect(demoBlocked(true, "people")).toBe(true);
    expect(demoBlocked(false, "people")).toBe(false);
    expect(demoBlocked(undefined, "ai_key")).toBe(false);
  });
  it("finds the current identity", () => {
    expect(currentIdentity(ids, "u1", "rep")?.as).toBe("u1");
    expect(currentIdentity(ids, null, "admin")?.as).toBe("admin");
  });
  it("keeps the page unless a rep lands on admin", () => {
    expect(landingPath("/w/t/deals", "t", "rep")).toBe("/w/t/deals");
    expect(landingPath("/w/t/admin", "t", "rep")).toBe("/w/t/home");
    expect(landingPath("/w/t/admin", "t", "admin")).toBe("/w/t/admin");
    expect(landingPath("/welcome", "t", "admin")).toBe("/w/t/home");
  });
});
