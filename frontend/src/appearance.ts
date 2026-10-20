// Per-viewer appearance preferences (Settings > Appearance). They only change how the app looks,
// never what it computes, and live in this browser (localStorage), like the theme.
export type Density = "comfortable" | "compact";
export type TextSize = "standard" | "large";
export type Motion = "system" | "reduced";
export interface Appearance { density: Density; text: TextSize; motion: Motion }

export const APPEARANCE_KEY = "df-appearance";
export const DEFAULT_APPEARANCE: Appearance = { density: "comfortable", text: "standard", motion: "system" };

type Store = Pick<Storage, "getItem" | "setItem">;
function defaultStore(): Store | null { try { return localStorage; } catch { return null; } }

/** Stored preferences; anything missing or invalid falls back to the default value. */
export function readAppearance(store: Store | null = defaultStore()): Appearance {
  try {
    const raw = JSON.parse(store?.getItem(APPEARANCE_KEY) ?? "{}") as Partial<Record<keyof Appearance, unknown>>;
    return {
      density: raw.density === "compact" ? "compact" : "comfortable",
      text: raw.text === "large" ? "large" : "standard",
      motion: raw.motion === "reduced" ? "reduced" : "system",
    };
  } catch { return { ...DEFAULT_APPEARANCE }; }
}

export function saveAppearance(a: Appearance, store: Store | null = defaultStore()): void {
  try { store?.setItem(APPEARANCE_KEY, JSON.stringify(a)); } catch { /* unavailable: lasts for this page only */ }
}

/** Sets data-density / data-text / data-motion on <html>; defaults remove the attribute. */
export function applyAppearance(a: Appearance, root: { dataset: Record<string, string | undefined> } = document.documentElement): void {
  const set = (k: string, v: string, def: string) => { if (v === def) delete root.dataset[k]; else root.dataset[k] = v; };
  set("density", a.density, "comfortable");
  set("text", a.text, "standard");
  set("motion", a.motion, "system");
}
