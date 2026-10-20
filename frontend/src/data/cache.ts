/** In-memory response cache shared by `useQuery` and `request` (no dependency). */

export const FRESH_MS = 30_000;

interface Entry { data: unknown; at: number }
const entries = new Map<string, Entry>();
const listeners = new Set<(prefix: string) => void>();

export function cacheGet(key: string): Entry | undefined { return entries.get(key); }
export function cacheSet(key: string, data: unknown): void {
  entries.set(key, { data, at: Date.now() });
  if (entries.size > 300) entries.delete(entries.keys().next().value as string); // oldest first
}
export function isFresh(e: Entry | undefined, now = Date.now()): boolean {
  return !!e && now - e.at < FRESH_MS;
}
export function cacheClear(): void { entries.clear(); }

/** Drop every cached response whose key starts with `prefix` and tell mounted queries to refetch. */
export function invalidate(prefix: string): void {
  for (const k of [...entries.keys()]) if (k.startsWith(prefix)) entries.delete(k);
  listeners.forEach((l) => l(prefix));
}
export function onInvalidate(fn: (prefix: string) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
