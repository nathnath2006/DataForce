export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${i === 0 ? v : v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${Math.round(s - m * 60)} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** What each recorded AI purpose is, in the user's words (the org-chart AI pass records its calls
 *  as "explanation"). Unknown purposes are shown as recorded. */
const PURPOSES: Record<string, string> = {
  title_classification: "Job titles",
  explanation: "Org statements from meetings",
  assistant: "Assistant questions",
  theme_naming: "Theme names",
  embedding: "Embeddings",
};
export function purposeLabel(p: string): string {
  return PURPOSES[p] ?? p;
}
