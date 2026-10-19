import { describe, expect, it } from "vitest";
import { isSafeMailAuthorizeUrl, mailboxReason, shortAddress, statusKind } from "./logic";

describe("mailbox logic", () => {
  it("accepts only the provider's own https host", () => {
    expect(isSafeMailAuthorizeUrl("https://accounts.google.com/o/oauth2/v2/auth?x=1", "gmail")).toBe(true);
    expect(isSafeMailAuthorizeUrl("https://login.microsoftonline.com/common/oauth2/v2.0/authorize", "outlook")).toBe(true);
    expect(isSafeMailAuthorizeUrl("https://accounts.google.com.evil.example/x", "gmail")).toBe(false);
    expect(isSafeMailAuthorizeUrl("http://accounts.google.com/x", "gmail")).toBe(false);
    expect(isSafeMailAuthorizeUrl("https://u:p@accounts.google.com/x", "gmail")).toBe(false);
    expect(isSafeMailAuthorizeUrl("https://accounts.google.com/x", "outlook")).toBe(false);
    expect(isSafeMailAuthorizeUrl("not a url", "gmail")).toBe(false);
  });
  it("never echoes an unknown reason", () => {
    expect(mailboxReason("denied")).toContain("denied");
    expect(mailboxReason("<script>")).toBe("The sign-in failed.");
    expect(mailboxReason(null)).toBe("The sign-in failed.");
  });
  it("shortens long addresses and maps statuses", () => {
    expect(shortAddress("a@b.co")).toBe("a@b.co");
    expect(shortAddress("x".repeat(60)).length).toBe(38);
    expect(statusKind("needs_reconnect")).toBe("bad");
    expect(statusKind("connected")).toBe("ok");
  });
});
