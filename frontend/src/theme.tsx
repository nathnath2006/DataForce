import { useEffect, useState } from "react";
import { applyAppearance, readAppearance } from "./appearance";

export type ThemeChoice = "system" | "light" | "dark";
export const THEME_KEY = "df-theme";
const ORDER: ThemeChoice[] = ["system", "light", "dark"];

type Store = Pick<Storage, "getItem" | "setItem">;

export function nextTheme(t: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(t) + 1) % ORDER.length] ?? "system";
}

function defaultStore(): Store | null {
  try { return localStorage; } catch { return null; }
}

/** Stored choice; anything missing, invalid or unreadable means "system". */
export function readTheme(store: Store | null = defaultStore()): ThemeChoice {
  try {
    const v = store?.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch { return "system"; }
}

export function saveTheme(t: ThemeChoice, store: Store | null = defaultStore()): void {
  try { store?.setItem(THEME_KEY, t); } catch { /* unavailable: the choice lasts for this page only */ }
}

export function applyTheme(t: ThemeChoice, root: { dataset: Record<string, string | undefined> } = document.documentElement): void {
  if (t === "system") delete root.dataset["theme"];
  else root.dataset["theme"] = t;
}

/** Called from main.tsx before the first render. */
export function initTheme(): void {
  applyTheme(readTheme());
  applyAppearance(readAppearance());
}

/** The applied theme (follows the toggle): for widgets that take an explicit mode. */
export function useThemeChoice(): ThemeChoice {
  const read = (): ThemeChoice => {
    const t = document.documentElement.dataset["theme"];
    return t === "light" || t === "dark" ? t : "system";
  };
  const [t, setT] = useState<ThemeChoice>(read);
  useEffect(() => {
    const obs = new MutationObserver(() => setT(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return t;
}

const LABEL: Record<ThemeChoice, string> = { system: "System", light: "Light", dark: "Dark" };

/** Saves and applies a theme choice (top-bar toggle and Settings > Appearance stay in step through data-theme). */
export function setThemeChoice(t: ThemeChoice): void { saveTheme(t); applyTheme(t); }

export function ThemeToggle() {
  const t = useThemeChoice();
  const n = nextTheme(t);
  return (
    <button
      type="button" className="theme-toggle"
      aria-label={`Theme: ${LABEL[t]}. Switch to ${LABEL[n]}.`} title={`Theme: ${LABEL[t]}`}
      onClick={() => setThemeChoice(n)}
    >
      Theme: {LABEL[t]}
    </button>
  );
}
