import type { MailProvider } from "./types";

const AUTH_HOSTS: Record<MailProvider, string> = {
  gmail: "accounts.google.com",
  outlook: "login.microsoftonline.com",
};

/** True only for an https sign-in URL on the provider's own host, without credentials. */
export function isSafeMailAuthorizeUrl(url: string, provider: MailProvider): boolean {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && u.hostname === AUTH_HOSTS[provider] && !u.username && !u.password;
  } catch {
    return false;
  }
}

const REASONS = new Map<string, string>([
  ["denied", "You denied access on the provider's page."],
  ["expired", "The sign-in took too long (10 minutes). Try again."],
  ["invalid_state", "The sign-in could not be matched to this browser. Start it again from this page."],
  ["exchange_failed", "The provider refused the sign-in. Check the client id, the secret and the redirect address."],
  ["server_error", "The sign-in failed. Try again."],
]);

/** A fixed sentence for the `reason` the callback put in the address. Unknown values are not echoed. */
export function mailboxReason(reason: string | null): string {
  return (reason && REASONS.get(reason)) || "The sign-in failed.";
}

/** The part of an address before the @ is kept; the rest is shown as is. Display only. */
export function shortAddress(addr: string): string {
  return addr.length > 40 ? `${addr.slice(0, 37)}…` : addr;
}

export function statusKind(status: string): "ok" | "warn" | "mute" | "bad" {
  if (status === "connected") return "ok";
  if (status === "needs_reconnect") return "bad";
  return status === "configured" ? "warn" : "mute";
}

export function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}
