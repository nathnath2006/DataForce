import { api } from "../api";
import { cacheSet, invalidate } from "./cache";
import type { WorkspaceOut } from "../types";

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Call `load` until `found(value)` is true (at most `tries` times, `delayMs` apart). A failed call is
 * retried; the last failure is thrown. Returns the last value and whether it satisfied `found`.
 */
export async function refreshUntil<V>(
  load: () => Promise<V>, found: (v: V) => boolean,
  o: { tries?: number; delayMs?: number; sleep?: (ms: number) => Promise<void> } = {},
): Promise<{ value: V; ok: boolean }> {
  const { tries = 10, delayMs = 400, sleep = wait } = o;
  let last: { value: V } | null = null;
  for (let i = 0; i < tries; i++) {
    try {
      const value = await load();
      last = { value };
      if (found(value)) return { value, ok: true };
    } catch (e) {
      if (i === tries - 1) throw e;
    }
    if (i < tries - 1) await sleep(delayMs);
  }
  if (!last) throw new Error("no answer");
  return { value: last.value, ok: false };
}

/**
 * After creating a workspace: drop the cached list, then wait until a fresh list holds `slug`, so the
 * next screen never reads a stale (empty) cache and shows a false "not found".
 */
export async function refreshWorkspacesUntil(slug: string): Promise<boolean> {
  invalidate("/workspaces");
  const { value, ok } = await refreshUntil<WorkspaceOut[]>(() => api.listWorkspaces(), (l) => l.some((w) => w.slug === slug));
  cacheSet("/workspaces", value);
  invalidate("/workspaces"); // mounted lists refetch the same answer
  return ok;
}
