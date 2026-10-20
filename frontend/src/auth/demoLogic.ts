import type { DemoIdentity } from "./demoTypes";

export const DEMO_BLOCKED_REASON = "Not available in the demo";

export type DemoFeature =
  | "access_codes" | "people" | "ai_key" | "tamtam" | "mailbox" | "data_connections"
  | "workspace_create" | "workspace_delete" | "limits_edit";

const BLOCKED: ReadonlySet<DemoFeature> = new Set<DemoFeature>([
  "access_codes", "people", "ai_key", "tamtam", "mailbox", "data_connections",
  "workspace_create", "workspace_delete", "limits_edit",
]);

/** True when the feature is refused by the server in a demo session (UX hint only; the server is the guard). */
export function demoBlocked(isDemo: boolean | undefined, feature: DemoFeature): boolean {
  return !!isDemo && BLOCKED.has(feature);
}

/** Admin first, then reps by name. */
export function sortIdentities(list: readonly DemoIdentity[]): DemoIdentity[] {
  return [...list].sort((a, b) =>
    (a.role === "admin" ? 0 : 1) - (b.role === "admin" ? 0 : 1) || a.label.localeCompare(b.label));
}

/** "Demo admin" or "Name (rep)" style label for the menu button. */
export function identityLabel(i: DemoIdentity): string {
  return i.role === "admin" || /\(.*\)/.test(i.label) ? i.label : `${i.label} (rep)`;
}

/** The identity the session currently is, matched on the app user id (reps) or admin role. */
export function currentIdentity(list: readonly DemoIdentity[], appUserId: string | null | undefined, role: string | undefined): DemoIdentity | null {
  return list.find((i) => (appUserId && i.as === appUserId) || (!appUserId && i.role === "admin" && role === "admin")) ?? null;
}

/** Where to land after switching identity: same page, except admin-only pages for a rep. */
export function landingPath(pathname: string, slug: string, role: "admin" | "rep"): string {
  const home = `/w/${slug}/home`;
  if (!pathname.startsWith(`/w/${slug}/`)) return home;
  if (role === "rep" && /^\/w\/[^/]+\/admin(\/|$)/.test(pathname)) return home;
  return pathname;
}
